class VisualPlanContractTestsPart01(VisualPlanContractBase):
    def test_coverage_conflict_is_saved_as_a_chat_clarification(self):
        module = self.application_module
        conflict = module.visual_plan_geometry.PlanGeometryError(
            'إجمالي بصمات المباني يتجاوز نسبة التغطية المسجلة.',
            'PLANS_COVERAGE_CONFLICT')
        contract = {
            'landArea': 1000, 'coverageRatio': 30,
            'distribution': {'rows': [{'component': 'فلل سكنية', 'floor_area_sqm': 150}]},
        }
        context = {'components': []}
        program = {'buildings': [
            {'id': f'villa_{index}', 'name': 'فلل سكنية', 'footprintArea': 150,
             'basementOnly': False}
            for index in range(3)
        ]}
        data = {'message': 'ليه المخطط وقف؟', 'plansWorkflow': {'siteAssistant': {}}}
        model_replies = [
            ({'question': 'هل تريد مراجعة مساحات الفلل أم نسبة التغطية المسجلة؟',
              'choices': ['مساحات الفلل', 'نسبة التغطية'], 'memory': 'يوجد تعارض بين البصمات وحد التغطية.'}, 20),
            ({'question': 'ما المساحة التي تريد مراجعتها في التوزيع المعتمد؟',
              'choices': [], 'memory': 'العميل يريد مراجعة مساحات الفلل.'}, 15),
        ]

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=conflict), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='same-approved-inputs'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=model_replies) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                first, first_status = module._visual_plan_site_assistant_execute(data, 'generate')
                followup_data = {
                    'message': 'راجع مساحات الفلل',
                    'plansWorkflow': {'siteAssistant': first['assistantState']},
                }
                second, second_status = module._visual_plan_site_assistant_execute(followup_data, 'chat')
                model_call.side_effect = RuntimeError('provider unavailable')
                fallback_data = {
                    'message': 'ما زال التعارض موجودًا',
                    'plansWorkflow': {'siteAssistant': second['assistantState']},
                }
                fallback, fallback_status = module._visual_plan_site_assistant_execute(
                    fallback_data, 'chat')

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(fallback_status, 200)
        self.assertTrue(first['success'])
        self.assertTrue(first['needsClarification'])
        self.assertEqual(first['coverageConflict']['coverageCapSqm'], 300)
        self.assertEqual(first['coverageConflict']['requiredFootprintTotalSqm'], 450)
        self.assertEqual(first['coverageConflict']['buildingGroups'][0]['count'], 3)
        self.assertFalse(first['assistantState']['generateRequested'])
        self.assertEqual(second['assistantState']['answers'], [{
            'question': first['question'], 'answer': 'راجع مساحات الفلل',
        }])
        second_packet = json.loads(model_call.call_args_list[1].args[1])
        self.assertEqual(second_packet['coverageConflict']['coverageCapSqm'], 300)
        self.assertIn('راجع مساحات الفلل', second_packet['latestClientMessage'])
        self.assertFalse(second['readyForGeneration'])
        self.assertTrue(fallback['success'])
        self.assertTrue(fallback['needsClarification'])
        self.assertIn('حد التغطية', fallback['question'])
        generate.assert_not_called()
