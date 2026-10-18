class VisualPlanContractTestsPart01(VisualPlanContractBase):
    def test_coverage_conflict_is_saved_as_a_chat_clarification(self):
        module = self.application_module
        project = {'approved_financial_area': 1000, 'approved_coverage_ratio': 30,
                   'project_components_data': [{'name': 'فلل سكنية', 'units': 3,
                                                'unitFootprintArea': 150}]}
        data = {'projectData': project, 'message': 'ليه المخطط وقف؟', 'plansWorkflow': {
            'distribution': {'rows': [{'id': 'villa-row', 'component': 'فلل سكنية',
                                       'floor_range': '1-2', 'floor_area_sqm': 150}]},
            'siteAssistant': {},
        }}
        model_reply = {'ready': False, 'conflict': True,
                       'reply': 'إجمالي البصمات يتجاوز نسبة التغطية المسجلة.',
                       'question': 'هل تريد مراجعة مساحات الفلل أم نسبة التغطية؟',
                       'choices': ['مساحات الفلل', 'نسبة التغطية'],
                       'memory': 'يوجد تعارض بين البصمات وحد التغطية.'}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_scene_from_request', side_effect=AssertionError(
                    'The site chat must not call the geometry validator')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'The site chat must not calculate a placement program')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 20)) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        self.assertFalse(hasattr(module, '_visual_plan_site_conflict_interview'))
        self.assertEqual(status, 200)
        self.assertTrue(result['needsClarification'])
        self.assertIn('إجمالي البصمات يتجاوز نسبة التغطية المسجلة.', result['reply'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['validatedProjectData']['projectMeasurements']['landAreaSqm'], 1000)
        self.assertEqual(sent['validatedProjectData']['distributionRows'][0]['floor_area_sqm'], 150)
        self.assertTrue(result['assistantState']['generateRequested'] is False)
        generate.assert_not_called()

    def test_individual_villa_program_uses_the_per_unit_footprint_field(self):
        module = self.application_module
        contract = {'distribution': {'rows': [{
            'id': 'villa_row', 'building': 'الفلل', 'component': 'فلل سكنية',
            'floor_range': 'G+1', 'units_per_floor': 100, 'floor_area_sqm': 13000,
            'circulation': '',
        }]}}
        context = {'components': module._visual_concept_components({
            'financial_study_model': {'dynamicRows': {'components': [{
                'id': 'villa_component', 'name': 'فلل سكنية', 'useType': 'residential',
                'units': 100, 'unitArea': 260, 'unitFootprintArea': 105,
                'builtArea': 26000, 'floorRange': 'G+1',
            }]}}
        })}

        program = module._visual_plan_program(contract, context)

        self.assertEqual(len(program['buildings']), 100)
        self.assertEqual(sum(item['footprintArea'] for item in program['buildings']), 10500)
        self.assertTrue(all(item['footprintArea'] == 105 for item in program['buildings']))

    def test_footprint_source_question_reads_component_notes_and_asks_for_confirmation(self):
        module = self.application_module
        project = {'approved_financial_area': 10000,
                   'financial_study_model': {'dynamicRows': {'components': [{
                       'id': 'villa_component', 'name': 'فلل سكنية', 'useType': 'residential',
                       'units': 100, 'unitArea': 260, 'builtArea': 26000,
                       'floorRange': 'G+1', 'notes': 'البصمة الإجمالية 10500 م²',
                   }]}}}
        data = {'projectData': project, 'message': 'هو انت جبت مساحة الفلل منين؟',
                'plansWorkflow': {'distribution': {'rows': [{
                    'id': 'villa-row', 'component': 'فلل سكنية', 'floor_range': 'G+1',
                    'floor_area_sqm': 26000, 'notes': 'البصمة الإجمالية 10500 م²',
                }]}, 'siteAssistant': {}}}
        model_reply = {
            'ready': False,
            'reply': 'المسجل 26,000 م² على 100 فيلا وعلى دورين، وملاحظة المكون 10,500 م².',
            'question': 'أي قيمة تمثل بصمة الفيلا الواحدة الصحيحة؟', 'choices': [],
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                    'The site chat must not calculate geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'Argon must receive source areas without derived footprints')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 50)) as model_call:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        self.assertEqual(status, 200)
        self.assertIn('26,000 م²', result['reply'])
        self.assertIn('10,500 م²', result['reply'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['validatedProjectData']['financialComponents'][0]['notes'],
                         'البصمة الإجمالية 10500 م²')
        self.assertIn('البصمة الإجمالية 10500 م²',
                      sent['validatedProjectData']['distributionRows'][0]['notes'])

    def test_footprint_correction_without_a_recorded_value_asks_for_the_unit_area(self):
        module = self.application_module
        project = {'project_components_data': [{'name': 'فلل سكنية', 'units': 100,
                                                'builtArea': 26000, 'floorRange': 'G+1'}]}
        data = {'projectData': project, 'message': 'مساحة بصمة الفيلا غير دقيقة',
                'plansWorkflow': {'distribution': {'rows': [{
                    'id': 'villa-row', 'component': 'فلل سكنية', 'floor_range': 'G+1',
                    'floor_area_sqm': 26000,
                }]}, 'siteAssistant': {'pendingQuestion': 'ما الرقم غير الدقيق؟'}}}
        data['plansWorkflow']['siteAssistant']['inputSignature'] = \
            module._visual_plan_site_context_signature(data)
        model_reply = {'ready': False, 'reply': 'فهمت أن بصمة الفيلا الحالية غير دقيقة.',
                       'question': 'ما مساحة البصمة الصحيحة للفيلا الواحدة؟', 'choices': []}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                    'The site chat must not calculate geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'Argon must receive source areas without derived footprints')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 50)) as model_call:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        self.assertEqual(status, 200)
        self.assertIn('ما مساحة البصمة الصحيحة للفيلا الواحدة', result['question'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['resolvedAnswers'][0]['answer'], 'مساحة بصمة الفيلا غير دقيقة')
