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
        self.assertEqual(result['engine'], 'image_generation')
        self.assertEqual(captured['references'], [])
        self.assertIn('VERTICAL PROGRAM DISTRIBUTION', captured['prompt'])

    def test_plan_massing_attaches_plan_one_as_2d_reference_and_prompts_heights_extrusion(self):
        module = self.application_module
        project = self.project()
        workflow = {
            'distribution': {
                'approved': True,
                'rows': [
                    {'building': 'Building A', 'floor_range': 'G-5', 'component': 'Commercial',
                     'units_per_floor': 2, 'floor_area_sqm': 400, 'circulation': ''},
                ]
            }
        }
        data = {
            'projectData': project,
            'plansWorkflow': workflow,
            'planImages': {
                'site': '/uploads/creative/tenant/plan_site.svg',
            },
        }
        captured = {}

        def _fake_images_call(prompt, references, **_kwargs):
            captured['prompt'] = prompt
            captured['references'] = list(references or [])
            return 'data:image/png;base64,MASSING_IMAGE_DATA'

        with patch.object(module, 'call_images_api', side_effect=_fake_images_call), \
                patch.object(module, '_visual_concept_reference_uris',
                             side_effect=lambda urls=None, **_kwargs: list(urls or [])), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/massing.png'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data, 'plan_massing')

        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/massing.png')
        self.assertEqual(result['engine'], 'image_generation')
        self.assertIn('/uploads/creative/tenant/plan_site.svg', captured['references'])
        self.assertIn('STRICT COMPOSITION', captured['prompt'])
        self.assertIn('Plan 1', captured['prompt'])

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
