class VisualPlanContractTestsPart06(VisualPlanContractBase):
    def test_setback_conflict_enters_the_site_chat_with_actionable_choices(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {
            'buildings': [
                {'id': 'building_1', 'name': 'Tower A', 'footprintArea': 450, 'basementOnly': False},
            ],
            'siteItems': [],
        }
        error_msg = (
            'تم رفض التصميم لأن بصمة أحد المباني في المشروع (مثل Building 1 أو Main Building أو '
            'Tower B أو Tower A أو Villas) تتجاوز حدود الارتداد المسجلة. القاعدة المخالفة هي عدم '
            'الالتزام بالارتدادات المطلوبة (3.0 شمالاً وجنوباً وغرباً، و5.0 شرقاً).'
        )
        error = module.visual_plan_geometry.PlanGeometryError(error_msg, 'PLANS_SETBACK_CONFLICT')
        data = {'message': 'ارسم المخطط العام الآن', 'plansWorkflow': {'siteAssistant': {}}}

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'The initial setback conflict must be surfaced without depending on the chat provider')) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                first, status = module._visual_plan_site_assistant_execute(data, 'generate')

        model_call.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(first['success'])
        self.assertTrue(first['needsClarification'])
        self.assertFalse(first['readyForGeneration'])
        self.assertEqual(first['setbackConflict']['code'], 'PLANS_SETBACK_CONFLICT')
        self.assertEqual(first['setbackConflict']['setbacks'], {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0})
        self.assertIn('تتجاوز حدود الارتداد المسجلة', first['reply'])
        self.assertIn('كيف تفضل المتابعة', first['reply'])
        self.assertTrue(any('إعادة توزيع المواضع آلياً' in choice for choice in first['choices']))
        self.assertTrue(any('مراجعة مساحات بصمات المباني' in choice for choice in first['choices']))
        self.assertTrue(any('مراجعة الارتدادات المسجلة' in choice for choice in first['choices']))
        self.assertEqual(first['assistantState']['turns'][-1]['role'], 'assistant')
        self.assertFalse(first['assistantState']['generateRequested'])

    def test_setback_inquiry_explains_footprint_cause_in_chat(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {
            'buildings': [
                {'id': 'building_1', 'name': 'Tower A', 'footprintArea': 450, 'basementOnly': False},
            ],
            'siteItems': [],
        }
        error = module.visual_plan_geometry.PlanGeometryError('تجاوز الارتدادات', 'PLANS_SETBACK_CONFLICT')
        first_state = {
            'inputSignature': 'setback-conflict',
            'pendingQuestion': 'كيف تفضل المتابعة؟',
            'turns': [{'role': 'assistant', 'text': 'كيف تفضل المتابعة؟'}],
        }
        data = {
            'message': 'هو في مشكله ان المساعد مش بيقولي الخطاء في الشات عشان ابداء اتناقش معاه اصلا لاكن هو فعلا الحدود صح 3 شمال و جنوب وغرب و 5 شرق',
            'plansWorkflow': {'siteAssistant': first_state},
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'), \
                    patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                        'Setback inquiries must be answered deterministically from facts')) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertTrue(result['needsClarification'])
        self.assertIn('الارتدادات المسجلة', result['reply'])
        self.assertIn('حرم البناء', result['reply'])
        self.assertIn('لا تتسع لمجموع بصمات المباني', result['reply'])
        self.assertTrue(any('إعادة توزيع المواضع آلياً' in choice for choice in result['choices']))
        self.assertTrue(any('مراجعة مساحات بصمات المباني' in choice for choice in result['choices']))

    def test_setback_placement_retry_request_triggers_generate(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {'buildings': [{'id': 'b1', 'name': 'Tower', 'footprintArea': 200}], 'siteItems': []}
        error = module.visual_plan_geometry.PlanGeometryError('تجاوز الارتداد', 'PLANS_SETBACK_CONFLICT')
        first_state = {
            'inputSignature': 'setback-conflict',
            'pendingQuestion': 'كيف تفضل المتابعة؟',
            'turns': [{'role': 'assistant', 'text': 'كيف تفضل المتابعة؟'}],
        }
        data = {
            'message': 'إعادة توزيع المواضع آلياً',
            'plansWorkflow': {'siteAssistant': first_state},
        }

        generated_result = {'success': True, 'svgCode': '<svg></svg>', 'image': '/test.svg'}
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'), \
                    patch.object(module, '_visual_plan_site_generate', return_value=generated_result) as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        generate.assert_called_once()

    def test_setback_auto_retry_failed_asks_for_review(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {'buildings': [{'id': 'b1', 'name': 'Tower', 'footprintArea': 200}], 'siteItems': []}
        error = module.visual_plan_geometry.PlanGeometryError('تجاوز الارتداد', 'PLANS_SETBACK_CONFLICT')
        retry_error = module.visual_plan_geometry.PlanGeometryError('لا يزال يتجاوز الارتداد', 'PLANS_SETBACK_CONFLICT')
        first_state = {
            'inputSignature': 'setback-conflict',
            'pendingQuestion': 'كيف تفضل المتابعة؟',
            'turns': [{'role': 'assistant', 'text': 'كيف تفضل المتابعة؟'}],
        }
        data = {
            'message': 'إعادة توزيع المواضع آلياً',
            'plansWorkflow': {'siteAssistant': first_state},
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'), \
                    patch.object(module, '_visual_plan_site_generate', side_effect=retry_error) as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertTrue(result['needsClarification'])
        self.assertIn('أعدت محاولة التوزيع آليًا', result['reply'])
        self.assertTrue(any('مراجعة مساحات بصمات المباني' in choice for choice in result['choices']))
        self.assertTrue(any('مراجعة الارتدادات المسجلة' in choice for choice in result['choices']))
