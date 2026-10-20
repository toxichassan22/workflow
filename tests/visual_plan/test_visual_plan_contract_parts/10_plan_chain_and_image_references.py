import base64
import json
import re


class VisualPlanContractTestsPart10(VisualPlanContractBase):
    """The image pipeline and the diagram chain.

    Two rules live here. No SVG may reach the images provider — it answers
    "unsupported mimetype ('image/svg+xml')" and kills the whole call, which
    the client could only report as the generic "تعذر توليد الصورة". And the
    diagrams build on each other in a fixed order: Plan 2 on Plan 1, Plan 3 on
    Plan 1 and Plan 2, and the exterior render on Plan 3 alone.
    """

    def test_an_svg_reference_is_rasterized_before_the_images_api_sees_it(self):
        module = self.application_module
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
               '<rect x="0" y="0" width="40" height="20" fill="#123456"/></svg>')
        data_uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')

        prepared = module._normalize_image_references([data_uri], tenant_id=self.tenant_a)

        self.assertEqual(len(prepared), 1)
        self.assertTrue(prepared[0].startswith('data:image/png;base64,'))
        self.assertNotIn('svg+xml', prepared[0][:64])

    def test_a_reference_type_the_images_api_refuses_never_leaves_the_server(self):
        module = self.application_module
        gif = 'data:image/gif;base64,' + base64.b64encode(b'GIF89a').decode('ascii')

        prepared = module._normalize_image_references([gif], tenant_id=self.tenant_a)

        self.assertEqual(prepared, [])

    def test_the_exterior_render_is_grounded_on_the_massing_diagram_only(self):
        module = self.application_module
        facts = {
            'plan_image_map': {
                'site': '/uploads/creative/tenant/plan1.svg',
                'uses': '/uploads/creative/tenant/plan2.svg',
                'massing': '/uploads/creative/tenant/plan3.svg',
            },
            'overview_map_url': '/uploads/maps/site.png',
            'style_reference_file_ids': [],
        }
        with patch.object(module, '_visual_concept_reference_uris',
                          side_effect=lambda urls=None, **_kwargs: list(urls or [])), \
                self.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            cover_refs = module._visual_concept_collect_generation_references(facts, 'cover')

        self.assertIn('/uploads/creative/tenant/plan3.svg', cover_refs)
        self.assertNotIn('/uploads/creative/tenant/plan1.svg', cover_refs)
        self.assertNotIn('/uploads/creative/tenant/plan2.svg', cover_refs)

    def test_an_exterior_angle_keeps_the_massing_and_the_hero_only(self):
        module = self.application_module
        facts = {'plan_image_map': {'massing': '/uploads/creative/tenant/plan3.svg'}}
        with patch.object(module, '_visual_concept_reference_uris',
                          side_effect=lambda urls=None, **_kwargs: list(urls or [])), \
                self.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            refs = module._visual_concept_collect_generation_references(
                facts, 'right', '/uploads/creative/tenant/cover.png')

        self.assertEqual(refs, ['/uploads/creative/tenant/plan3.svg',
                                '/uploads/creative/tenant/cover.png'])

    def test_the_exterior_prompt_binds_the_render_to_the_approved_massing(self):
        module = self.application_module
        facts = {'plan_image_map': {'massing': '/uploads/creative/tenant/plan3.svg'}}

        suffix = module._visual_concept_exterior_conformity_suffix(
            'Show the building.', facts, 'cover')

        self.assertTrue(suffix.startswith('Show the building.'))
        self.assertIn('approved massing diagram (Plan 3)', suffix)
        self.assertIn('do not change any count, number, dimension or area', suffix.lower())
        self.assertIn('Do not invent anything that is not in it', suffix)
        # An interior slot is not bound to the exterior rule.
        self.assertEqual(
            module._visual_concept_exterior_conformity_suffix(
                'Show the room.', facts, 'interior_comp-1'), 'Show the room.')

    def test_plan_two_is_drawn_on_plan_one_and_plan_three_on_both(self):
        module = self.application_module
        data = {'planImages': {
            'site': '/uploads/creative/tenant/plan1.svg',
            'uses': '/uploads/creative/tenant/plan2.svg',
            'massing': '/uploads/creative/tenant/plan3.svg',
        }}

        self.assertEqual(module._visual_plan_dependency_images(data, {}, 'uses'),
                         ['/uploads/creative/tenant/plan1.svg'])
        self.assertEqual(module._visual_plan_dependency_images(data, {}, 'massing'),
                         ['/uploads/creative/tenant/plan1.svg',
                          '/uploads/creative/tenant/plan2.svg'])

    def test_the_massing_render_attaches_plan_one_and_plan_two(self):
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': []})
        with patch.object(module, 'call_openrouter_chat', return_value={
                'choices': [{'message': {'content': layout}}]
        }), patch.object(module, 'persist_generated_image',
                        return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                scene, _context, _ref = module._visual_plan_create_scene({
                    'projectData': project, 'plansWorkflow': workflow})
        data = {
            'projectData': project,
            'plansWorkflow': {**workflow, 'scene': scene},
            'planImages': {
                'site': '/uploads/creative/tenant/plan1.svg',
                'uses': '/uploads/creative/tenant/plan2.svg',
            },
        }
        captured = {}

        def _fake_call(prompt, references, **_kwargs):
            captured['prompt'] = prompt
            captured['references'] = [str(item) for item in (references or [])]
            return 'data:image/png;base64,AAAA'

        with patch.object(module, 'call_images_api', side_effect=_fake_call), \
                patch.object(module, '_visual_concept_reference_uris',
                             side_effect=lambda urls=None, **_kwargs: list(urls or [])), \
                patch.object(module, 'persist_generated_image',
                             return_value='/uploads/creative/tenant/plan3.png'), \
                patch.object(module, '_visual_concept_edit_base_image', return_value=''), \
                patch.object(module, '_visual_concept_render_plan_boundary_reference',
                             return_value=''):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                result = module._visual_plan_render_response(data, 'plan_massing')

        self.assertTrue(result['success'])
        self.assertEqual(result['scene']['token'], scene['token'])
        self.assertIn('/uploads/creative/tenant/plan1.svg', captured['references'])
        self.assertIn('/uploads/creative/tenant/plan2.svg', captured['references'])
        self.assertIn('STRICT COMPOSITION', captured['prompt'])
        self.assertIn('Plan 1', captured['prompt'])
        self.assertIn('Plan 2', captured['prompt'])

    def test_the_uses_render_is_a_floor_allocation_and_not_an_isometric(self):
        module = self.application_module

        prompt = module._visual_plan_dependency_prompt('uses', ['site'], base_image=False)

        self.assertIn('STRICT DERIVATION', prompt)
        self.assertIn('floor-by-floor', prompt)
        self.assertIn('Plan 1', prompt)
        self.assertNotIn('isometric', prompt.lower())
        self.assertNotIn('Plan 2', prompt)

    def test_the_massing_prompt_is_english_whatever_the_project_language(self):
        module = self.application_module
        context = {
            'project_name': 'مشروع النخيل',
            'city': 'الرياض',
            'district': 'حي الملقا',
            'components': [{'id': 'c1', 'name': 'فلل سكنية', 'useType': 'residential',
                            'units': 10, 'builtArea': 500}],
        }

        prompt = module._visual_concept_plan_drawing_prompt('massing', context)

        self.assertNotIn('اسم المشروع', prompt)
        self.assertNotIn('نوع الصورة المطلوبة', prompt)
        self.assertIn('DRAWING REQUESTED: conceptual massing', prompt)
        self.assertIn('Write every label of the drawing in English', prompt)
        self.assertIn('Every word in the drawing is English', prompt)
        self.assertIn('never with the recorded Arabic text', prompt)

    def test_the_massing_prompt_keeps_a_latin_project_name(self):
        module = self.application_module
        context = {'project_name': 'Al Waha Compound', 'city': 'Riyadh',
                   'district': 'Al Malqa', 'components': []}

        prompt = module._visual_concept_plan_drawing_prompt('massing', context)

        self.assertIn('PROJECT: Al Waha Compound — Riyadh, Al Malqa', prompt)

    def test_the_uses_prompt_is_english_whatever_the_project_language(self):
        module = self.application_module
        context = {
            'project_name': 'مشروع النخيل',
            'city': 'الرياض',
            'district': 'حي الملقا',
            'components': [{'id': 'c1', 'name': 'فلل سكنية', 'useType': 'residential',
                            'units': 10, 'builtArea': 500}],
        }

        prompt = module._visual_concept_plan_drawing_prompt('uses', context)

        self.assertNotIn('اسم المشروع', prompt)
        self.assertNotIn('نوع الصورة المطلوبة', prompt)
        self.assertIn('DRAWING REQUESTED: vertical program', prompt)
        self.assertIn('Write every label of the drawing in English', prompt)
        self.assertIn('Every word in the drawing is English', prompt)
        self.assertIn('VERTICAL PROGRAM DISTRIBUTION', prompt)
