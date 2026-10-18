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

    def test_setback_conflict_background_job_completes_with_interactive_chat(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {'buildings': [{'id': 'b1', 'name': 'Tower A', 'footprintArea': 450, 'basementOnly': False}], 'siteItems': []}
        error_msg = 'تم رفض التصميم لأن بصمة أحد المباني تتجاوز حدود الارتداد المسجلة.'
        error = module.visual_plan_geometry.PlanGeometryError(error_msg, 'PLANS_SETBACK_CONFLICT')
        data = {'message': '', 'plansWorkflow': {'siteAssistant': {}}}
        actor = {'tenant_id': self.tenant_a, 'user_role': 'admin',
                 'token_payload': {'exp': module.time.time() + 3600}}
        job_id = 'test-setback-job-1'
        initial_job = {'status': 'queued', 'createdAt': module.time.time()}

        written_jobs = {}
        def mock_write_job(namespace, tenant_id, jid, job_dict):
            written_jobs[jid] = dict(job_dict)

        def mock_read_job(namespace, tenant_id, jid):
            return dict(written_jobs.get(jid, initial_job))

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_write_job', side_effect=mock_write_job), \
                    patch.object(module, '_read_job', side_effect=mock_read_job), \
                    patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='sig-1'), \
                    patch.object(module, '_landloom_can', return_value=True), \
                    patch.object(module.db, 'get_tenant_by_id', return_value={'id': self.tenant_a, 'is_active': True}), \
                    patch.object(module.auth, '_load_token_user', return_value=({'id': 'u1', 'role': 'admin'}, None)), \
                    patch.object(module.auth, '_session_state_error', return_value=None), \
                    patch.object(module.db, 'get_user_permissions', return_value={'generate_images': True}):
                module._visual_plan_job_worker(module.app, actor, data, 'site_chat', 'plan_site', job_id)

        final_job = written_jobs.get(job_id)
        self.assertIsNotNone(final_job)
        self.assertEqual(final_job['status'], 'completed')
        self.assertTrue(final_job['success'])
        self.assertEqual(final_job['httpStatus'], 200)
        self.assertTrue(final_job['result']['success'])
        self.assertTrue(final_job['result']['needsClarification'])
        self.assertEqual(final_job['result']['choices'],
                         ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة'])

    def test_shared_ground_components_footprint_and_coverage_resolution(self):
        module = self.application_module
        # Case 1: Tower A has 600 showrooms + 625 hall on ground floor -> 1225 m²
        # Tower B has 600 showrooms + 440 hall on ground floor -> 1040 m²
        rows_conflicted = [
            {'id': 'r1', 'building': 'البرج أ', 'floor_range': 'أرضي', 'component': 'معارض', 'floor_area_sqm': 600},
            {'id': 'r2', 'building': 'البرج أ', 'floor_range': 'أرضي', 'component': 'صالة أفراح', 'floor_area_sqm': 625},
            {'id': 'r3', 'building': 'البرج ب', 'floor_range': 'أرضي', 'component': 'معارض', 'floor_area_sqm': 600},
            {'id': 'r4', 'building': 'البرج ب', 'floor_range': 'أرضي', 'component': 'صالة أفراح', 'floor_area_sqm': 440},
            {'id': 'r5', 'building': 'مبنى الفلل', 'floor_range': 'أرضي', 'component': 'فلل سكنية', 'floor_area_sqm': 10500},
        ]
        by_bld_conflicted = {}
        for r in rows_conflicted:
            parsed = module._visual_concept_plan_floor_range(r['floor_range'])
            by_bld_conflicted.setdefault(r['building'], []).append((parsed, r))

        req_conflicted = module._visual_concept_plan_required_footprints(by_bld_conflicted)
        self.assertEqual(req_conflicted, 1225 + 1040 + 10500)

        # Case 2: User balances Tower A ground floor to 600 + 440 = 1040 m²,
        # and moves the remaining 185 m² of hall to mezzanine
        rows_resolved = [
            {'id': 'r1', 'building': 'البرج أ', 'floor_range': 'أرضي', 'component': 'معارض', 'floor_area_sqm': 600},
            {'id': 'r2', 'building': 'البرج أ', 'floor_range': 'أرضي', 'component': 'صالة أفراح', 'floor_area_sqm': 440},
            {'id': 'r2b', 'building': 'البرج أ', 'floor_range': 'ميزانين', 'component': 'صالة أفراح', 'floor_area_sqm': 185},
            {'id': 'r3', 'building': 'البرج ب', 'floor_range': 'أرضي', 'component': 'معارض', 'floor_area_sqm': 600},
            {'id': 'r4', 'building': 'البرج ب', 'floor_range': 'أرضي', 'component': 'صالة أفراح', 'floor_area_sqm': 440},
            {'id': 'r5', 'building': 'مبنى الفلل', 'floor_range': 'أرضي', 'component': 'فلل سكنية', 'floor_area_sqm': 10500},
        ]
        by_bld_resolved = {}
        for r in rows_resolved:
            parsed = module._visual_concept_plan_floor_range(r['floor_range'])
            by_bld_resolved.setdefault(r['building'], []).append((parsed, r))

        req_resolved = module._visual_concept_plan_required_footprints(by_bld_resolved)
        self.assertEqual(req_resolved, 1040 + 1040 + 10500)

    def test_natural_arabic_setback_parsing_resolves_without_false_conflicts(self):
        import visual_plan_context
        rows = [
            {'direction': 'east', 'setback': '5م'},
            {'direction': 'north', 'setback': '3م'},
            {'direction': 'south', 'setback': '3م'},
            {'direction': 'west', 'setback': '3م'},
        ]
        test_phrases = [
            '3 شمال و جنوب وغرب و 5 شرق',
            '3م شمال وجنوب وغرب و5م شرق',
            '3م شمال وجنوب وغرب و 5م شرق',
            'ارتداد 3م لجميع الجهات عدا الشرق 5م',
            'الارتدادات: 3م شمال وجنوب وغرب، 5م شرق',
            '3م من جميع الجهات',
        ]
        for phrase in test_phrases:
            result = visual_plan_context.recorded_setbacks(phrase, rows, 'east')
            self.assertEqual(result.get('east'), 5.0, f'East failed on {phrase}')
            self.assertEqual(result.get('north'), 3.0, f'North failed on {phrase}')
            self.assertEqual(result.get('south'), 3.0, f'South failed on {phrase}')
            self.assertEqual(result.get('west'), 3.0, f'West failed on {phrase}')

    def test_notes_review_surfaces_geometry_error_as_actionable_check_item(self):
        module = self.application_module
        data = {'plansWorkflow': {'clientNotes': 'ملاحظة عامة'}}
        with patch.object(module, '_visual_plan_contract',
                          side_effect=module.visual_plan_geometry.PlanGeometryError('قيم الارتدادات المسجلة متعارضة.', 'PLANS_SETBACK_CONFLICT')):
            review, frontage = module._visual_plan_review_notes(data)

        self.assertTrue(review['verified'])
        self.assertFalse(review['canProceed'])
        self.assertEqual(len(review['checks']), 1)
        self.assertEqual(review['checks'][0]['result'], 'متعارض')
        self.assertIn('قيم الارتدادات المسجلة متعارضة', review['checks'][0]['detail'])
        self.assertEqual(frontage['status'], 'unresolved')


