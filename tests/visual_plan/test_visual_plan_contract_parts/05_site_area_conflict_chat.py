class VisualPlanContractTestsPart05(VisualPlanContractBase):
    def test_parking_area_conflict_enters_the_site_chat_with_actionable_choices(self):
        module = self.application_module
        project = {'approved_financial_area': 1000, 'croquis_land_area': 1000,
                   'project_components_data': [{'id': 'parking', 'name': 'Parking',
                                                'units': 30, 'builtArea': 500,
                                                'notes': 'Keep the visitor spaces near the entrance.'}]}
        data = {'projectData': project, 'message': 'ارسم المخطط الآن', 'plansWorkflow': {
            'distribution': {'rows': [{'id': 'parking-row', 'building': 'Site',
                                       'component': 'Parking', 'floor_range': 'مواقف سطحية',
                                       'floor_area_sqm': 500, 'notes': 'Separate visitor parking.'}]},
            'distributionNotes': 'Keep service access clear.', 'siteAssistant': {},
        }}
        model_reply = {'ready': False, 'conflict': True,
                       'reply': 'قد تتعارض مساحة المواقف المطلوبة مع مساحة الموقع المتاحة.',
                       'question': 'هل المساحة المعتمدة للمواقف 500 م²؟',
                       'choices': ['تأكيد مساحة المواقف', 'مراجعة التوزيع']}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_scene_from_request', side_effect=AssertionError(
                    'The site chat must not validate placement geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'The site chat must not calculate building placement')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 40)) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                first, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        generate.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(first['success'])
        self.assertTrue(first['needsClarification'])
        self.assertFalse(first['readyForGeneration'])
        self.assertEqual(first['question'], model_reply['question'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['validatedProjectData']['financialComponents'][0]['builtArea'], 500)
        self.assertEqual(sent['validatedProjectData']['distributionNotes'], 'Keep service access clear.')
        self.assertFalse(first['assistantState']['generateRequested'])

    def test_parking_area_dispute_turn_asks_for_the_replacement_value(self):
        module = self.application_module
        project = {'approved_financial_area': 1000, 'project_components_data': [
            {'id': 'parking', 'name': 'Parking', 'builtArea': 500, 'units': 30}]}
        data = {'projectData': project, 'message': 'مساحة Parking غير دقيقة',
                'plansWorkflow': {'siteAssistant': {}}}
        first_state = {
            'inputSignature': module._visual_plan_site_context_signature(data),
            'pendingQuestion': 'ما الذي نراجعه؟',
            'turns': [{'role': 'assistant', 'text': 'ما الذي نراجعه؟'}],
        }
        data['plansWorkflow']['siteAssistant'] = first_state
        model_reply = {'reply': 'سأراجع قيمة المواقف معك.',
                       'question': 'ما المساحة الصحيحة المعتمدة لـ«Parking»؟', 'choices': []}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 50)) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        generate.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertTrue(result['needsClarification'])
        self.assertIn('ما المساحة الصحيحة المعتمدة لـ«Parking»', result['question'])
        self.assertEqual(result['assistantState']['answers'], [{
            'question': 'ما الذي نراجعه؟', 'answer': 'مساحة Parking غير دقيقة',
        }])
        self.assertFalse(result['assistantState']['readyForGeneration'])

    def test_parking_area_source_question_answers_from_the_approved_distribution(self):
        module = self.application_module
        project = {'approved_financial_area': 1000,
                   'project_components_data': [{'id': 'parking', 'name': 'Parking',
                                                'units': 30, 'builtArea': 500}]}
        data = {'projectData': project, 'message': 'هو انت جبت مساحة Parking منين؟',
                'plansWorkflow': {'distribution': {'rows': [{
                    'id': 'parking-row', 'component': 'Parking', 'floor_range': 'سطحي',
                    'units_per_floor': 30, 'floor_area_sqm': 500,
                }]}, 'siteAssistant': {}}}
        model_reply = {'ready': False, 'reply': 'المساحة المعتمدة لبند المواقف في التوزيع هي 500 م².',
                       'question': 'هل قيمة Parking صحيحة أم تحتاج مراجعة؟', 'choices': []}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                    'The site chat must not calculate geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'Argon reads distribution areas directly')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 50)) as model_call:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
        self.assertEqual(status, 200)
        self.assertIn('المساحة المعتمدة لبند المواقف في التوزيع', result['reply'])
        self.assertIn('500 م²', result['reply'])
        self.assertIn('هل قيمة Parking صحيحة', result['question'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['validatedProjectData']['distributionRows'][0]['floor_area_sqm'], 500)

    def test_area_sufficient_placement_request_retries_without_asking_client_to_layout(self):
        module = self.application_module
        project = {'approved_financial_area': 24906.43,
                   'project_components_data': [{'name': 'Parking', 'builtArea': 9000}]}
        first_data = {'projectData': project, 'message': 'مناقشة توزيع Parking داخل الأرض',
                      'plansWorkflow': {'distributionNotes': 'Preserve access to all buildings.',
                                        'siteAssistant': {}}}
        model_reply = {'ready': True, 'generateRequested': True,
                       'redesignRequested': True,
                       'reply': 'سأعيد توزيع المواقف وفق المساحات المسجلة.',
                       'question': '', 'choices': []}
        generated = {'success': True, 'reply': 'تم إنشاء المخطط لمراجعته.', 'svgCode': '<svg/>'}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 60)) as model_call, \
                    patch.object(module, '_visual_plan_site_generate', return_value=generated) as generate:
                result, status = module._visual_plan_site_assistant_execute(first_data, 'chat')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertEqual(result['reply'], generated['reply'])
        self.assertTrue(result['svgCode'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertIn('Preserve access to all buildings.',
                      sent['validatedProjectData']['distributionNotes'])
        generate.assert_called_once()
