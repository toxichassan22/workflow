class VisualPlanContractTestsPart05(VisualPlanContractBase):
    def test_parking_area_conflict_enters_the_site_chat_with_actionable_choices(self):
        module = self.application_module
        contract = {
            'landArea': 1000, 'coverageRatio': 40,
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {
            'buildings': [
                {'id': 'building_a', 'name': 'Tower A', 'footprintArea': 300,
                 'basementOnly': False},
                {'id': 'building_b', 'name': 'Tower B', 'footprintArea': 250,
                 'basementOnly': False},
            ],
            'siteItems': [{'id': 'parking', 'name': 'Parking', 'label': 'Parking',
                           'siteType': 'parking', 'area': 500}],
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'المساحة المعتمدة «Parking» لا تتسع داخل حدود الأرض مع البصمات المسجلة.',
            'PLANS_SITE_AREA_CONFLICT')
        data = {'message': 'ارسم المخطط الآن', 'plansWorkflow': {'siteAssistant': {}}}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='parking-conflict'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'The initial geometry conflict must be surfaced without depending on the chat provider')) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                first, status = module._visual_plan_site_assistant_execute(data, 'generate')

        model_call.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(first['success'])
        self.assertTrue(first['needsClarification'])
        self.assertFalse(first['readyForGeneration'])
        self.assertEqual(first['siteAreaConflict']['failingSiteItem']['areaSqm'], 500)
        self.assertEqual(first['siteAreaConflict']['requiredFootprintTotalSqm'], 550)
        self.assertIn('مساحة «Parking» المسجلة 500 م²', first['reply'])
        self.assertIn('إجمالي بصمات المباني المسجلة 550 م²', first['reply'])
        self.assertTrue(any('مراجعة مساحة Parking' in choice for choice in first['choices']))
        self.assertTrue(any('بصمات المباني' in choice for choice in first['choices']))
        self.assertFalse(first['assistantState']['generateRequested'])

    def test_parking_area_dispute_turn_asks_for_the_replacement_value(self):
        module = self.application_module
        contract = {'landArea': 1000, 'distribution': {'rows': []}}
        context = {'components': []}
        program = {
            'buildings': [{'id': 'building_a', 'name': 'Tower A', 'footprintArea': 300,
                           'basementOnly': False}],
            'siteItems': [{'id': 'parking', 'name': 'Parking', 'label': 'Parking',
                           'siteType': 'parking', 'area': 500}],
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'المساحة المعتمدة «Parking» لا تتسع داخل حدود الأرض مع البصمات المسجلة.',
            'PLANS_SITE_AREA_CONFLICT')
        first_state = {
            'inputSignature': 'parking-conflict', 'pendingQuestion': 'ما الذي نراجعه؟',
            'turns': [{'role': 'assistant', 'text': 'ما الذي نراجعه؟'}],
        }
        data = {'message': 'مساحة Parking غير دقيقة',
                'plansWorkflow': {'siteAssistant': first_state}}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='parking-conflict'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'An explicit area dispute must ask for its replacement value')) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_not_called()
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
        contract = {'landArea': 1000, 'distribution': {'rows': []}}
        context = {'components': []}
        program = {
            'buildings': [],
            'siteItems': [{'id': 'parking', 'name': 'Parking', 'label': 'Parking',
                           'siteType': 'parking', 'area': 500}],
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'المساحة المعتمدة «Parking» لا تتسع داخل حدود الأرض مع البصمات المسجلة.',
            'PLANS_SITE_AREA_CONFLICT')
        data = {
            'message': 'هو انت جبت مساحة Parking منين؟',
            'plansWorkflow': {'siteAssistant': {
                'inputSignature': 'parking-conflict', 'pendingQuestion': 'ما الذي نراجعه أولًا؟',
                'turns': [{'role': 'assistant', 'text': 'ما الذي نراجعه أولًا؟'}],
            }},
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='parking-conflict'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'A source question should use the approved distribution value')) as model_call:
                result = module._visual_plan_site_conflict_interview(data, error)

        model_call.assert_not_called()
        self.assertIn('المساحة المعتمدة لبندها في التوزيع', result['reply'])
        self.assertIn('500 م²', result['reply'])
        self.assertIn('هل قيمة «Parking» صحيحة', result['question'])
