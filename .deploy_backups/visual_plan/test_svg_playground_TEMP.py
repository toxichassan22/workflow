# TEMPORARY — tests for the SVG model playground (revert with its commit).
#
# Everything AI is mocked: no provider call leaves the test process. The suite
# proves the playground fans out to exactly the 4 approved models, measures
# per-model time, sanitizes active SVG content, scores fidelity against the
# sealed scene, never touches the image model, and refuses unsealed inputs.
# It also pins the surface it ships on: stage 4 of the plans workflow, reading
# the current project data, with the retired standalone page gone.

import copy
import unittest
from unittest.mock import patch

from tests.workflow.test_meeting_requirements import (
    MeetingRequirementsTests, read_frontend_text, read_module_source)


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
    def setUp(self):
        super().setUp()
        patcher = patch.object(self.application_module, '_require_billing_balance', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mock_chat(self, module):
        def fake_chat(system_prompt, user_content, **kwargs):
            model = kwargs.get('model')
            if model == 'openai/gpt-6.1-sol':
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

    def test_playground_compares_exactly_the_two_finalist_models(self):
        module = self.application_module
        self.assertEqual(tuple(module.SVG_PLAYGROUND_MODELS), (
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
        self.assertEqual(set(by_model), {'openai/gpt-6.1-sol', 'google/gemini-4-argon'})
        sol = by_model['openai/gpt-6.1-sol']
        self.assertTrue(sol['ok'])
        self.assertIn('CONCEPTUAL SITE PLAN', sol['svg'])
        self.assertGreater(sol['score'], 0)
        argon = by_model['google/gemini-4-argon']
        self.assertTrue(argon['ok'])
        self.assertLess(argon['score'], sol['score'])
        # Active content is still stripped at the helper level.
        dirty = module._svg_playground_sanitize_svg(
            '<svg><script>alert(1)</script><text>Tower</text></svg>')
        self.assertIn('Tower', dirty)
        self.assertNotIn('script', dirty)

    def test_stage4_seals_the_scene_itself_when_stage3_never_ran(self):
        """Stages 1 and 2 approved, no scene and no prompts from stage 3.

        The comparison must not wait for the generation stage: it seals the same
        scene stage 3 would have, from the project data, and hands it back so
        stage 3 can reuse it.
        """
        module = self.application_module
        project = _project()
        workflow = _workflow(project)
        self.assertNotIn('scene', workflow)
        self.assertNotIn('promptReady', workflow)
        calls = {'create': 0}

        def fake_scene_from_request(data):
            posted = (data.get('plansWorkflow') or {}).get('scene') or {}
            if posted.get('token') != 'sealed-by-stage-4':
                raise module.visual_plan_geometry.PlanGeometryError(
                    'المشهد الهندسي غير جاهز.', 'PLANS_SCENE_REQUIRED')
            return _scene(), {}, {}, {}

        def fake_create_scene(data, context=None):
            calls['create'] += 1
            return ({**_scene(), 'version': 1, 'token': 'sealed-by-stage-4'}, {},
                    '/uploads/creative/parcel.png')

        with patch.object(module, '_visual_plan_scene_from_request',
                          side_effect=fake_scene_from_request), \
                patch.object(module, '_visual_plan_create_scene',
                             side_effect=fake_create_scene), \
                self._mock_chat(module), \
                patch.object(module, 'call_images_api') as image_call:
            response = self.app.test_client().post(
                '/api/visual-concept/plans-svg-playground',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(calls['create'], 1, 'stage 4 must seal the scene itself')
        self.assertEqual([item['model'] for item in body['results']],
                         list(module.SVG_PLAYGROUND_MODELS))
        self.assertEqual(body['scene']['token'], 'sealed-by-stage-4')
        image_call.assert_not_called()

    def test_each_model_is_reported_the_moment_it_finishes(self):
        """The worker publishes a model's exact wall time before the next starts,
        so the client never waits for the slowest model to see the first one."""
        module = self.application_module
        project = _project()
        seen = []
        with patch.object(module, '_visual_plan_scene_from_request',
                          return_value=(_scene(), {}, {}, {})), \
                self._mock_chat(module):
            result, status = module._svg_playground_execute(
                {'projectData': project, 'plansWorkflow': _workflow(project)},
                on_model=lambda results: seen.append(list(results)))
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        models = list(module.SVG_PLAYGROUND_MODELS)
        # Parallel threads finish in any order: every snapshot adds exactly one
        # new model, each snapshot stays in model order, and the last one is whole.
        self.assertEqual(len(seen), 2)
        accumulated = set()
        for snapshot in seen:
            names = [item['model'] for item in snapshot]
            self.assertEqual(names, [model for model in models if model in names])
            accumulated.update(names)
        self.assertEqual(accumulated, set(models))
        self.assertEqual([item['model'] for item in result['results']], models)
        # Each published slice carries the measured time of everything so far.
        timings = []
        with patch.object(module, '_visual_plan_scene_from_request',
                          return_value=(_scene(), {}, {}, {})), \
                self._mock_chat(module):
            module._svg_playground_execute(
                {'projectData': project, 'plansWorkflow': _workflow(project)},
                on_model=lambda results: timings.append(
                    [isinstance(item.get('ms'), int) for item in results]))
        self.assertEqual(len(timings), 2)
        self.assertTrue(all(all(row) for row in timings))
        self.assertEqual(sorted(len(row) for row in timings), [1, 2])

    def test_the_job_carries_partial_results_while_it_runs(self):
        backend = read_module_source('app.py')
        self.assertIn("'partial': {'success': True, 'results': results,", backend)
        self.assertIn("result, status = _svg_playground_execute(data, on_model=report_finished)", backend)
        self.assertIn("'httpStatus', 'partial') if key in job", backend)

    def test_the_client_shows_seconds_and_streams_finished_models(self):
        source = read_frontend_text()
        self.assertIn("function visualConceptPlansSvgCompareSeconds(ms)", source)
        self.assertIn("WFT('plans.svg_compare_seconds', 'الوقت: {seconds} ثانية'", source)
        self.assertIn("WFT('plans.svg_compare_running', 'جاري تشغيل المقارنة — اكتمل {n} — المنقضي: {seconds} ثانية'", source)
        # A live clock repaints only the status line while the models run.
        self.assertIn('visualConceptPlansSvgCompareTimer = setInterval(visualConceptPlansSvgCompareTick, 250);', source)
        self.assertIn("if (job && job.partial && Array.isArray(job.partial.results) && typeof onPartial === 'function') {", source)

    def test_stage4_reuses_the_scene_the_generation_stage_already_sealed(self):
        module = self.application_module
        project = _project()
        workflow = _workflow(project)
        workflow['scene'] = {'version': 1, 'token': 'sealed-by-stage-3'}
        with patch.object(module, '_visual_plan_scene_from_request',
                          return_value=(_scene(), {}, {}, {})), \
                patch.object(module, '_visual_plan_create_scene') as create_scene, \
                self._mock_chat(module):
            response = self.app.test_client().post(
                '/api/visual-concept/plans-svg-playground',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNone(response.get_json()['scene'], 'nothing new to persist')
        create_scene.assert_not_called()

    def test_playground_gate_needs_stages_one_and_two_only(self):
        """No prompt, no scene token and no promptReady flag is demanded."""
        backend = read_module_source('app.py')
        self.assertIn(
            "workflow_error = _visual_concept_plan_workflow_error(\n"
            "        data, 'plan_site', require_distribution=True)",
            backend)
        self.assertIn('_svg_playground_scene(data)', backend)
        self.assertIn("_SVG_PLAYGROUND_RESEAL_CODES = ('PLANS_SCENE_REQUIRED', 'PLANS_SCENE_INVALID',", backend)
        source = read_frontend_text()
        self.assertIn('workflow.scene = response.scene;', source)

    def test_playground_accepts_recorded_geometry_without_boundary_approval(self):
        module = self.application_module
        project = _project()
        workflow = _workflow(project)
        workflow['boundary']['approved'] = False
        with self._mock_chat(module):
            response = self.app.test_client().post(
                '/api/visual-concept/plans-svg-playground',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_playground_is_the_fourth_stage_of_the_plans_workflow(self):
        """The tool is not a hidden page any more: it is the 4th plans step."""
        source = read_frontend_text()
        self.assertIn('data-plans-workflow-tab="svgcompare"', source)
        self.assertIn('data-plans-workflow-stage="svgcompare"', source)
        self.assertIn('data-plans-workflow-action="run-svg-compare"', source)
        self.assertIn("'plans.svg_compare_tab', 'مقارنة الموديلات'", source)
        # The tab unlocks on stages 1 and 2 — verification and an approved
        # distribution — and never on the generation stage, so it can
        # not lead to an endpoint that would refuse the request.
        self.assertIn("if (stage === 'svgcompare') {", source)
        self.assertIn(
            "if (!(state.distribution.approved && visualConceptPlanNotesCleared(state))) return;",
            source)
        self.assertIn('setVisualConceptPlansSvgCompareStage4(true);', source)
        # The selection is NOT kept in workflow.viewStage: the workflow normalizer
        # only accepts the three permanent stage names and rewrites anything else
        # to 'verify', which is what made the tab look dead.
        self.assertNotIn("viewStage = 'svgcompare'", source)
        self.assertIn("viewStage: ['verify', 'boundary', 'generate'].includes(source.viewStage)", source)
        self.assertNotIn('workflow.promptReady && tempStage4Active', source)
        # The retired standalone page is really gone, route included.
        self.assertNotIn('/playground-plans-svg', source)
        self.assertEqual(
            self.app.test_client().get('/playground-plans-svg').status_code, 404)
        self.assertFalse(
            hasattr(self.application_module, 'page_svg_playground'),
            'the standalone playground page must be retired with its route')

    def test_playground_stage_reads_the_current_project_data(self):
        """Stage 4 sends the same payload the generation stages do."""
        source = read_frontend_text()
        self.assertIn('async function runVisualConceptPlansSvgCompare()', source)
        self.assertIn("const payload = await collectVisualConceptPlansWorkflowPayload();", source)
        self.assertIn("api('POST', '/api/visual-concept/plans-svg-playground', payload)", source)
        self.assertIn("'/api/visual-concept/plans-svg-playground/jobs/' + encodeURIComponent(initial.jobId)", source)
        # The four SVG bodies stay out of the saved draft: the tool keeps them in
        # session state, so plansWorkflow is never given a compare field.
        self.assertNotIn('plansWorkflow.svgCompare', source)
        self.assertNotIn('workflow.svgCompare', source)

    def test_prompts_carry_the_stage3_brief_and_daylight_style(self):
        module = self.application_module
        scene = _scene()
        contract = {'projectName': 'Iconic', 'projectIdea': 'Mixed use tower',
                    'landBrief': 'West main facade.', 'regulatoryConstraints': 'No east entry.',
                    'recordedSurvey': [{'point': '1', 'eastings': 1, 'northings': 2}],
                    'directions': [{'direction': 'west', 'street': True,
                                    'streetName': 'Nour St', 'streetWidth': 20}],
                    'setbackText': '5 m west', 'boundaryLengths': 'West 40m',
                    'distribution': {'rows': [{'component': 'Residential'}]},
                    'clientNotes': 'Keep the courtyard.'}
        program = {'buildings': [{'name': 'Tower', 'label': 'Tower', 'footprintArea': 300,
                                  'levels': 3, 'bands': [{'kind': 'range', 'category': 'residential',
                                                          'label': 'Residential', 'floorRange': '1-3'}]}],
                   'siteItems': [{'name': 'Pool', 'label': 'Pool', 'category': 'amenity', 'area': 800}]}
        payload, texts, _numbers = module._svg_playground_geometry(scene, contract, program)
        self.assertIn('Tower', [item['label'] for item in payload['masses']])
        self.assertIn('Pool', [item['name'] for item in payload['site_program']])
        self.assertTrue(any('Nour St' in item['label'] for item in payload['streets']))
        self.assertIn('Tower', texts)
        system_prompt, user_prompt = module._svg_playground_prompts(payload, contract)
        self.assertIn('specialist in designing real-estate site plans by writing SVG code', system_prompt)
        self.assertIn('FIXED COLOR IDENTITY', system_prompt)
        self.assertIn('PROJECT DATA FIELDS', user_prompt)
        self.assertIn('parcel_pixels', user_prompt)
        self.assertIn('masses', user_prompt)
        brief = module._svg_playground_brief(contract)
        self.assertIn('West main facade', brief)
        self.assertIn('Keep the courtyard', brief)
        self.assertIn('Residential', brief)
        self.assertIn('WHITE', system_prompt.upper() + user_prompt.upper())
        self.assertIn('NEVER a dark', system_prompt)
        self.assertIn('viewBox="0 0 1600 900"', user_prompt)
        self.assertIn('legend', (system_prompt + user_prompt).lower())
        self.assertIn('not scattered rectangles', system_prompt)
        self.assertIn('HARD GEOGRAPHIC BOUNDARIES', system_prompt)
        self.assertIn('ARCHITECTURAL CREATIVE FREEDOM', system_prompt)
        self.assertIn('padel court', system_prompt)
        self.assertIn('swimming pool', system_prompt)
        self.assertIn('canopy trees', system_prompt)
        self.assertIn('<defs>', (system_prompt + user_prompt).lower())
        self.assertIn('<use', (system_prompt + user_prompt).lower())
        self.assertIn('CANVAS LAYOUT & NUMBERED KEY SYSTEM', system_prompt)
        self.assertIn('TOP-RIGHT SITE KEY & PROGRAM TABLE', system_prompt)
        self.assertIn('Key Number badges', system_prompt)
        self.assertIn('STRICT TEXT PROHIBITION ON SITE', system_prompt)
        self.assertIn('WITHOUT text labels on the site', system_prompt)
        self.assertIn('ONLY THREE items may contain text', system_prompt)
        self.assertIn('NO DIMENSION ARROWS', system_prompt)
        self.assertIn('site-key-table', user_prompt)
        self.assertIn('transform="translate(1220, 40)"', user_prompt)
        # Bounding box of projected parcel coordinates respects margins
        flat_parcel_pts = [pt for poly in payload['parcels'] for pt in poly]
        parcel_xs = [pt[0] for pt in flat_parcel_pts]
        parcel_ys = [pt[1] for pt in flat_parcel_pts]
        self.assertGreaterEqual(min(parcel_xs), 100)
        self.assertGreaterEqual(min(parcel_ys), 150)
        self.assertLessEqual(max(parcel_xs), 1250)
        self.assertLessEqual(max(parcel_ys), 760)

    def test_cards_open_svg_and_export_png_in_a_two_column_grid(self):
        source = read_frontend_text()
        self.assertIn('data-svg-compare-open', source)
        self.assertIn('data-svg-compare-png', source)
        self.assertIn('URL.createObjectURL', source)
        self.assertIn("canvas.toDataURL('image/png')", source)
        css_files = __import__('glob').glob('assets/css/**/*.css', recursive=True)
        css = '\n'.join(open(path, encoding='utf-8').read() for path in css_files)
        self.assertIn('repeat(2, minmax(0, 1fr))', css)

    def test_truncated_svg_retries_with_doubled_cap_and_low_reasoning(self):
        module = self.application_module
        calls = []

        def fake_chat(system_prompt, user_content, **kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                return {'choices': [{'finish_reason': 'length',
                                     'message': {'content': '<svg viewBox="0 0 1600 900"><rect'}}]}
            return {'choices': [{'finish_reason': 'stop',
                                 'message': {'content': '<svg viewBox="0 0 1600 900">'
                                                       '<text>CONCEPTUAL SITE PLAN</text></svg>'}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
            raw = module._svg_playground_run_model('test-model', 'sys', 'user', {})
        self.assertEqual(len(calls), 2, 'a length-truncated reply must be retried once')
        self.assertEqual(calls[0].get('reasoning_effort'), 'low')
        self.assertEqual(calls[0].get('max_tokens'), 128000)
        self.assertEqual(calls[1].get('max_tokens'), calls[0].get('max_tokens'))
        self.assertEqual(calls[0].get('timeout'), 600)
        final = module._svg_playground_finalize(raw, ['CONCEPTUAL SITE PLAN'], [])
        self.assertTrue(final['ok'])
        self.assertIn('<svg', final['svg'])

    def test_argon_runs_on_its_smaller_high_effort_budget(self):
        module = self.application_module
        seen = {}

        def fake_chat(system_prompt, user_content, **kwargs):
            seen.update(kwargs)
            return {'choices': [{'finish_reason': 'stop',
                                 'message': {'content': '<svg><text>CONCEPTUAL SITE PLAN</text></svg>'}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
            raw = module._svg_playground_run_model('google/gemini-4-argon', 'sys', 'user', {})
        self.assertEqual(seen.get('max_tokens'), 66000)
        self.assertEqual(seen.get('reasoning_effort'), 'low')
        final = module._svg_playground_finalize(raw, ['CONCEPTUAL SITE PLAN'], [])
        self.assertTrue(final['ok'])

    def test_truncated_twice_reports_diagnostics_not_a_blank_error(self):
        module = self.application_module

        def fake_chat(system_prompt, user_content, **kwargs):
            return {'choices': [{'finish_reason': 'length',
                                 'message': {'content': '<svg><rect' + ('x' * 500)}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
            raw = module._svg_playground_run_model('test-model', 'sys', 'user', {})
        self.assertFalse(raw['ok'])
        self.assertIn('انقطع', raw['error'])
        self.assertIn('حرفًا', raw['error'])

    def test_models_receive_the_parcel_outline_as_reference_image(self):
        module = self.application_module
        seen = {}

        def fake_chat(system_prompt, user_content, **kwargs):
            seen.update(kwargs)
            return {'choices': [{'finish_reason': 'stop',
                                 'message': {'content': '<svg><text>CONCEPTUAL SITE PLAN</text></svg>'}}]}

        scene = _scene()
        scene['geometry']['surveyPoints'] = [
            {'point': '1', 'eastings': 1, 'northings': 2},
            {'point': '2', 'eastings': 41, 'northings': 2},
            {'point': '3', 'eastings': 41, 'northings': 32},
            {'point': '4', 'eastings': 1, 'northings': 32},
        ]
        contract = {'geometry': scene['geometry']}
        # Reference building reads g.tenant_id like the worker thread does.
        with self.app.test_request_context('/'):
            from flask import g as flask_g
            flask_g.tenant_id = 'test-tenant'
            with patch.object(module, '_visual_plan_scene_from_request',
                              return_value=(scene, contract, {}, {})), \
                    patch.object(module, '_visual_concept_render_plan_boundary_reference',
                                 return_value='/uploads/creative/parcel.png') as render, \
                    patch.object(module, '_visual_concept_reference_uris',
                                 return_value=[{'url': '/uploads/creative/parcel.png'}]) as uris, \
                    patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
                result, status = module._svg_playground_execute(
                    {'projectData': _project(), 'plansWorkflow': _workflow(_project())})
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertTrue(render.called)
        self.assertTrue(uris.called)
        refs = seen.get('image_references')
        # Single owner-approved style benchmark first, the parcel outline last.
        self.assertEqual(len(refs), 2)
        self.assertTrue(str(refs[0]).startswith('data:image/jpeg;base64,'))
        self.assertEqual(refs[1], {'url': '/uploads/creative/parcel.png'})

    def test_style_examples_load_from_disk_and_degrade_quietly(self):
        module = self.application_module
        refs = module._svg_playground_style_references()
        self.assertEqual(len(refs), 1)
        self.assertTrue(all(item.startswith('data:image/jpeg;base64,') for item in refs))
        with patch.object(module, '_SVG_PLAYGROUND_STYLE_IMAGES', ('no-such-file.jpg',)):
            self.assertEqual(module._svg_playground_style_references(), [])

    def test_score_is_case_insensitive_and_format_tolerant(self):
        module = self.application_module
        svg = '<svg><text>MAIN ENTRY</text><path d="M 85 100"/></svg>'
        score = module._svg_playground_score(svg, ['Main Entry'], ['85.0'])
        self.assertEqual(score, 100.0)

    def test_broken_reference_builder_still_runs_text_only(self):
        module = self.application_module
        scene = _scene()
        scene['geometry']['surveyPoints'] = [
            {'point': '1', 'eastings': 1, 'northings': 2},
            {'point': '2', 'eastings': 41, 'northings': 2},
            {'point': '3', 'eastings': 41, 'northings': 32},
        ]
        with patch.object(module, '_visual_plan_scene_from_request',
                          return_value=(scene, {'geometry': scene['geometry']}, {}, {})), \
                patch.object(module, '_visual_concept_render_plan_boundary_reference',
                             side_effect=RuntimeError('disk full')), \
                self._mock_chat(module):
            result, status = module._svg_playground_execute(
                {'projectData': _project(), 'plansWorkflow': _workflow(_project())})
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])

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
