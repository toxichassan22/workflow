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

    def test_area_sufficient_parking_failure_is_explained_as_a_search_limit(self):
        module = self.application_module
        contract = {
            'landArea': 24906.43, 'distribution': {'rows': []},
            'geometry': {'parcels': [{'polygon': [
                [0, 0], [250, 0], [250, 99.6518], [0, 99.6518],
            ]}]},
        }
        context = {'components': []}
        program = {
            'buildings': [
                {'id': 'tower_a', 'name': 'البرج أ', 'footprintArea': 1040,
                 'basementOnly': False},
                {'id': 'tower_b', 'name': 'البرج ب', 'footprintArea': 1040,
                 'basementOnly': False},
                *[{'id': f'villa_{index}', 'name': 'فلل سكنية', 'footprintArea': 105,
                   'basementOnly': False} for index in range(100)],
            ],
            'siteItems': [
                {'id': 'parking', 'label': 'Parking', 'name': 'Parking', 'area': 9000},
                {'id': 'pool', 'label': 'Swimming Pool', 'name': 'Pool', 'area': 800},
                {'id': 'padel', 'label': 'Padel Court', 'name': 'Padel', 'area': 200},
                {'id': 'playground', 'label': 'Children Playground', 'name': 'Playground', 'area': 200},
                {'id': 'landscape', 'label': 'Landscape', 'name': 'Landscape', 'area': 2007.3},
            ],
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'المساحة المعتمدة «Parking» لا تتسع داخل حدود الأرض مع البصمات المسجلة.',
            'PLANS_SITE_AREA_CONFLICT')
        first_data = {'message': 'ابدأ المخطط', 'plansWorkflow': {'siteAssistant': {}}}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='same-site-input'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'The area arithmetic and search limitation should be stated deterministically')):
                first, first_status = module._visual_plan_site_assistant_execute(first_data, 'generate')
                followup_data = {
                    'message': 'مناقشة توزيع Parking داخل الأرض',
                    'plansWorkflow': {'siteAssistant': first['assistantState']},
                }
                followup, followup_status = module._visual_plan_site_assistant_execute(
                    followup_data, 'chat')

        self.assertEqual(first_status, 200)
        self.assertEqual(followup_status, 200)
        self.assertEqual(first['siteAreaConflict']['aggregateAreaSurplusSqm'], 125.65)
        self.assertEqual(first['siteAreaConflict']['availableAreaBeforeFailingSqm'], 9125.65)
        self.assertTrue(first['siteAreaConflict']['aggregateAreaSufficient'])
        self.assertIn('لا يظهر عجز في مجموع المساحات', first['reply'])
        self.assertIn('لا يثبت استحالة وجود توزيع صالح', first['reply'])
        self.assertIn('فائض 125.65 م²', followup['reply'])
        self.assertIn('لم يجرّب إعادة ترتيبها', followup['reply'])
        self.assertNotIn('الفراغات المتبقية مجزأة', followup['reply'])
