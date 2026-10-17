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
        self.assertIn('1,000 م² × نسبة التغطية 30% = حد أقصى 300 م²', first['reply'])
        self.assertIn('التوزيع المعتمد عن الحد 150 م²', first['reply'])
        self.assertIn('3 × 150 م² لكل مبنى', first['reply'])
        self.assertIn('لا مجموع مساحات جميع الأدوار', first['reply'])
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
        self.assertIn('الرقم الذي ترى أنه غير دقيق', fallback['question'])
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
        contract = {'landArea': 10000, 'coverageRatio': 51,
                    'distribution': {'rows': []}}
        context = {'components': module._visual_concept_components({
            'financial_study_model': {'dynamicRows': {'components': [{
                'id': 'villa_component', 'name': 'فلل سكنية', 'useType': 'residential',
                'units': 100, 'unitArea': 260, 'builtArea': 26000,
                'floorRange': 'G+1', 'notes': 'البصمة الإجمالية 10500 م²',
            }]}}
        })}
        program = {'buildings': [
            {'id': f'villa_{index}', 'name': 'فلل سكنية', 'footprintArea': 130,
             'levels': 2, 'basementOnly': False}
            for index in range(100)
        ]}
        data = {
            'message': 'هو انت جبت مساحة الفلل منين؟',
            'plansWorkflow': {'siteAssistant': {}},
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'إجمالي بصمات المباني يتجاوز نسبة التغطية المسجلة.',
            'PLANS_COVERAGE_CONFLICT')

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='same-input'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'A source question should be answered from the component data')) as model_call:
                result = module._visual_plan_site_conflict_interview(data, error)

        model_call.assert_not_called()
        component = result['coverageConflict']['financialComponentInputs'][0]
        self.assertEqual(component['noteAggregateFootprintSqm'], 10500)
        self.assertEqual(component['noteDerivedFootprintPerUnitSqm'], 105)
        self.assertIn('26,000 م² على 100 فيلا وعلى 2 دور', result['reply'])
        self.assertIn('10,500 م²', result['reply'])
        self.assertIn('105 م² لكل فيلا', result['reply'])
        self.assertNotIn('سبب التعارض هو تجاوز حد التغطية', result['reply'])
        self.assertIn('أي قيمة تمثل بصمة الفيلا الواحدة الصحيحة؟', result['question'])
        self.assertFalse(result['readyForGeneration'])

    def test_footprint_correction_without_a_recorded_value_asks_for_the_unit_area(self):
        module = self.application_module
        contract = {'landArea': 1000, 'coverageRatio': 30,
                    'distribution': {'rows': []}}
        context = {'components': [{
            'id': 'villa_component', 'name': 'فلل سكنية', 'units': 100,
            'builtArea': 26000, 'floorRange': 'G+1',
        }]}
        program = {'buildings': [
            {'id': f'villa_{index}', 'name': 'فلل سكنية', 'footprintArea': 130,
             'levels': 2, 'basementOnly': False}
            for index in range(100)
        ]}
        data = {
            'message': 'مساحة بصمة الفيلا غير دقيقة',
            'plansWorkflow': {'siteAssistant': {'pendingQuestion': 'ما الرقم غير الدقيق؟'}},
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'إجمالي بصمات المباني يتجاوز نسبة التغطية المسجلة.',
            'PLANS_COVERAGE_CONFLICT')

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='same-input'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'A correction must ask for the missing replacement value')) as model_call:
                result = module._visual_plan_site_conflict_interview(data, error)

        model_call.assert_not_called()
        self.assertIn('ما مساحة البصمة الصحيحة للفيلا الواحدة', result['question'])
        self.assertNotIn('سبب التعارض هو تجاوز حد التغطية', result['reply'])
