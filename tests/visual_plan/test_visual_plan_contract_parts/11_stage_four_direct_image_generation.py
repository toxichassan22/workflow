from unittest.mock import patch


class VisualPlanContractTestsPart11(VisualPlanContractBase):
    """Stage 4 diagrams (uses and massing) direct image generation.

    Stage 4 does not require a sealed engineering scene or tokens.
    Plan uses takes the floor distribution table from stage 2 directly.
    Plan massing takes Plan 1 (the 2D site plan) as reference and extrudes
    the building volumes by their heights without adding any structures.
    """

    def test_plan_uses_generates_directly_from_distribution_rows_without_scene(self):
        module = self.application_module
        project = self.project()
        workflow = {
            'distribution': {
                'approved': True,
                'rows': [
                    {'building': 'Main Tower', 'floor_range': 'G-4', 'component': 'Retail & Offices',
                     'units_per_floor': 4, 'floor_area_sqm': 600, 'circulation': ''},
                    {'building': 'Main Tower', 'floor_range': '5-12', 'component': 'Residential Apartments',
                     'units_per_floor': 6, 'floor_area_sqm': 600, 'circulation': ''},
                ]
            }
        }
        data = {
            'projectData': project,
            'plansWorkflow': workflow,
        }
        captured = {}

        def _fake_images_call(prompt, references, **_kwargs):
            captured['prompt'] = prompt
            captured['references'] = list(references or [])
            return 'data:image/png;base64,USES_IMAGE_DATA'

        with patch.object(module, 'call_images_api', side_effect=_fake_images_call), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/uses.png'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data, 'plan_uses')

        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/uses.png')
        self.assertEqual(result['engine'], 'svg_stacking')
        self.assertEqual(captured['references'], [])
        self.assertIn('VERTICAL PROGRAM DISTRIBUTION', captured['prompt'])

    def test_plan_massing_generates_svg_from_plan1_and_plan2_svg(self):
        module = self.application_module
        project = self.project()
        fake_plan1_svg = '<svg viewBox="0 0 1600 1000"><rect id="hotel_tower" x="100" y="100" width="200" height="300" fill="#FEF08A"/><rect id="surface_parking" x="100" y="450" width="200" height="150" fill="#CBD5E1"/></svg>'
        fake_plan2_svg = '<svg viewBox="0 0 1600 1000"><text>Tower: 15 floors (G-14)</text></svg>'
        workflow = {
            'distribution': {
                'approved': True,
                'rows': [
                    {'building': 'Main Tower', 'floor_range': 'G-14', 'component': 'Hotel'},
                ]
            },
            'slots': {
                'plan_site': {'svgCode': fake_plan1_svg},
                'plan_uses': {'svgCode': fake_plan2_svg},
            }
        }
        data = {
            'projectData': project,
            'plansWorkflow': workflow,
        }
        captured = {}

        def _fake_chat_call(system, user, **_kwargs):
            captured['system'] = system
            captured['user'] = user
            fake_svg = '<svg viewBox="0 0 1600 1000"><polygon points="100,100 200,100 200,200" fill="#FEF08A"/></svg>'
            return {'choices': [{'message': {'content': fake_svg}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=_fake_chat_call), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/massing.svg'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data, 'plan_massing')

        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/massing.svg')
        self.assertEqual(result['engine'], 'svg_massing')
        self.assertEqual(result['model'], module.VISUAL_PLAN_MASSING_MODEL)
        self.assertIn('<polygon', result['svgCode'])
        # Assert Plan 1 SVG and Plan 2 SVG are fed directly into the prompt
        self.assertIn('PLAN 1 (MASTER SITE PLAN - EXACT VECTOR SVG LAYOUT)', captured['user'])
        self.assertIn('surface_parking', captured['user'])
        self.assertIn('PLAN 2 (VERTICAL PROGRAM DISTRIBUTION - EXACT FLOOR STACK SVG)', captured['user'])
        self.assertIn('Tower: 15 floors', captured['user'])

    def test_plan_massing_uses_the_compact_geometry_manifest_when_a_scene_exists(self):
        module = self.application_module
        project = self.project()
        workflow = {
            'scene': {
                'buildings': [{
                    'id': 'b1', 'label': 'Hotel Tower', 'category': 'hotel', 'levels': 15,
                    'footprint': [[100, 100], [300, 100], [300, 400], [100, 400]],
                }],
                'openAreas': [{
                    'label': 'Surface Parking', 'featureType': 'parking',
                    'polygon': [[100, 450], [300, 450], [300, 600], [100, 600]],
                }],
            },
            'distribution': {
                'approved': True,
                'rows': [{'building': 'Hotel Tower', 'floor_range': 'G-14', 'component': 'Hotel'}],
            },
        }
        data = {'projectData': project, 'plansWorkflow': workflow}
        captured = {}

        def _fake_chat_call(system, user, **_kwargs):
            captured['user'] = user
            fake_svg = '<svg viewBox="0 0 1600 1000"><polygon points="100,100 200,100 200,200"/></svg>'
            return {'choices': [{'message': {'content': fake_svg}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=_fake_chat_call), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/massing.svg'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data, 'plan_massing')

        self.assertTrue(result['success'])
        self.assertIn('AUTHORITATIVE GEOMETRY MANIFEST', captured['user'])
        self.assertIn('Hotel Tower', captured['user'])
        self.assertIn('Surface Parking', captured['user'])
        self.assertNotIn('PLAN 1 (MASTER SITE PLAN - EXACT VECTOR SVG LAYOUT)', captured['user'])

    def test_stage_four_workflow_error_bypasses_notes_and_scene_gates(self):
        module = self.application_module
        data = {
            'plansWorkflow': {
                'verification': {'approved': False},
                'distribution': {'approved': False},
            }
        }
        # Uses and massing bypass workflow blockers
        self.assertIsNone(module._visual_concept_plan_workflow_error(data, 'plan_uses', require_distribution=True))
        self.assertIsNone(module._visual_concept_plan_workflow_error(data, 'plan_massing', require_distribution=True))

        # Site plan still enforces the verification gate
        site_error = module._visual_concept_plan_workflow_error(data, 'plan_site', require_distribution=True)
        self.assertIsNotNone(site_error)
        self.assertEqual(site_error['error_code'], 'PLANS_VERIFICATION_REQUIRED')

    def test_stage_four_prompt_job_generates_from_distribution_without_scene_check(self):
        module = self.application_module
        project = self.project()
        workflow = {
            'distribution': {
                'approved': True,
                'rows': [
                    {'building': 'Tower A', 'floor_range': '1-6', 'component': 'Offices',
                     'units_per_floor': 3, 'floor_area_sqm': 300, 'circulation': ''},
                ]
            }
        }
        data = {'projectData': project, 'plansWorkflow': workflow}

        with self.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            uses_job = module._visual_plan_execute('prompt', data, 'plan_uses')
            massing_job = module._visual_plan_execute('prompt', data, 'plan_massing')

        uses_res = uses_job[0] if isinstance(uses_job, tuple) else uses_job
        massing_res = massing_job[0] if isinstance(massing_job, tuple) else massing_job
        self.assertTrue(uses_res.get('success'))
        self.assertIn('VERTICAL PROGRAM DISTRIBUTION', uses_res.get('prompt', ''))
        self.assertTrue(massing_res.get('success'))
        self.assertIn('CONCEPTUAL MASSING', massing_res.get('prompt', ''))

    def test_stage_four_render_handles_string_visual_concept_in_project_data(self):
        module = self.application_module
        # Case 1: visual_concept as a serialized JSON string
        data_json_str = {
            'projectData': {
                'visual_concept': json.dumps({
                    'slots': {
                        'plan_site': {'imageUrl': '/uploads/creative/tenant/plan_site.svg'},
                    }
                })
            },
            'plansWorkflow': {
                'prompts': {'massing': 'Prompt for massing'},
            }
        }
        captured = {}
        def fake_call_images_api(prompt, references=None, **kwargs):
            captured['prompt'] = prompt
            captured['references'] = list(references or [])
            return 'data:image/png;base64,fakeimage'

        with patch.object(module, 'call_images_api', side_effect=fake_call_images_api), \
                patch.object(module, '_visual_concept_reference_uris', side_effect=lambda urls, **kwargs: urls), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/massing.png'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data_json_str, 'plan_massing')

        self.assertTrue(result['success'])
        self.assertIn('/uploads/creative/tenant/plan_site.svg', captured['references'])

        # Case 2: visual_concept as a non-JSON string (must not crash with AttributeError)
        data_plain_str = {
            'projectData': {
                'visual_concept': 'some plain string status'
            },
            'plansWorkflow': {
                'prompts': {'massing': 'Prompt for massing'},
            }
        }
        with patch.object(module, 'call_images_api', side_effect=fake_call_images_api), \
                patch.object(module, '_visual_concept_reference_uris', side_effect=lambda urls, **kwargs: urls), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/massing.png'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result2 = module._visual_plan_render_response(data_plain_str, 'plan_massing')

        self.assertTrue(result2['success'])

    def test_plan_massing_edit_diagram_updates_svg_with_sol_model(self):
        module = self.application_module
        project = self.project()
        data = {
            'projectData': project,
            'plansWorkflow': {},
            'message': 'Make the tower facade light stone',
            'currentSvg': '<svg viewBox="0 0 1600 1000"><rect id="tower" width="100" height="100"/></svg>',
            'planImages': {
                'site': '/uploads/creative/tenant/plan_site.svg',
                'uses': '/uploads/creative/tenant/plan_uses.svg',
            }
        }
        captured = {}
        def fake_call_chat(system, user, **kwargs):
            captured['system'] = system
            captured['user'] = user
            return {'choices': [{'message': {'content': '<svg viewBox="0 0 1600 1000"><rect id="tower" width="100" height="150" fill="#F8FAFC"/></svg>'}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call_chat), \
                patch.object(module, '_visual_plan_extract_current_slot_svg', side_effect=lambda d, slot: '<svg id="' + slot + '"></svg>'), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/tenant/massing_v2.svg'):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_edit_diagram(data, 'plan_massing', 'massing')

        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/tenant/massing_v2.svg')
        self.assertEqual(result['engine'], 'svg_massing')
        self.assertIn('<rect id="tower"', result['svgCode'])
        self.assertIn('Make the tower facade light stone', captured['user'])
        self.assertIn('PLAN 1 (SITE PLAN SVG', captured['user'])
        self.assertIn('PLAN 2 (FLOOR DISTRIBUTION SVG', captured['user'])


