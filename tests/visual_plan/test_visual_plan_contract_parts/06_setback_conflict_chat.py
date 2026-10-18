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
            mock_model_response = {
                'reply': 'الارتدادات المسجلة صحيحة؛ والمشكلة أن حرم البناء المتبقي لا تتسع لمجموع بصمات المباني المطلوبة في الدور الأرضي.',
                'question': 'كيف تفضل المتابعة: هل نعيد محاولة التوزيع آليًا، أم ترغب في مراجعة بصمات المباني أو الارتدادات؟',
                'choices': ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة'],
            }
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'), \
                    patch.object(module, '_visual_plan_site_call', return_value=(mock_model_response, 50)) as model_call, \
                    patch.object(module, '_visual_plan_site_generate') as generate:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        model_call.assert_called_once()
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

    def test_setback_area_calculation_inquiry_returns_exact_numerical_breakdown(self):
        module = self.application_module
        # Land: 40x25 = 1000 sqm rectangle
        # Setbacks: 3m north, 3m south, 5m east, 3m west
        # Buildable rectangle: (40 - 5 - 3) = 32m width; (25 - 3 - 3) = 19m height.
        # Buildable area = 32 * 19 = 608 sqm.
        contract = {
            'landArea': 1000,
            'coverageRatio': 70,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        # Required footprint = 1040 sqm, which exceeds 608 sqm!
        program = {'buildings': [{'id': 'b1', 'name': 'Tower', 'footprintArea': 1040}], 'siteItems': []}
        error = module.visual_plan_geometry.PlanGeometryError(
            'المبنى «Tower» (1040 م²) لا تتسع داخل أي جزء متبقٍ من منطقة البناء بعد الارتدادات المسجلة.',
            'PLANS_SETBACK_CONFLICT')
        data = {
            'message': 'طيب احسبلي كده المساحه بالارتدادات كام ومساحه البصمه كام',
            'plansWorkflow': {'siteAssistant': {'turns': []}},
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'):
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        reply = result.get('reply') or ''
        self.assertTrue('حساب' in reply or 'الحسابات' in reply or 'المساحات' in reply)
        self.assertTrue('1,000' in reply or '1000' in reply)  # Total land area
        self.assertIn('608', reply)    # Net buildable area
        self.assertTrue('1,040' in reply or '1040' in reply)  # Required footprint
        self.assertIn('تتجاوز', reply)
        choices = result.get('choices') or []
        self.assertTrue(any(any(kw in c for kw in ('بصم', 'مبان', 'ارتداد', 'توزيع')) for c in choices) or len(choices) > 0)

    def test_setback_facts_contain_buildable_envelope_area_and_deduction(self):
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 70,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {'buildings': [{'id': 'b1', 'name': 'Tower', 'footprintArea': 500}], 'siteItems': []}
        error = module.visual_plan_geometry.PlanGeometryError('تجاوز الارتداد', 'PLANS_SETBACK_CONFLICT')
        data = {
            'message': 'كم المساحة المتبقية بعد الارتداد',
            'plansWorkflow': {'siteAssistant': {'turns': []}},
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-conflict'):
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

        self.assertEqual(status, 200)
        reply = result.get('reply') or ''
        self.assertIn('608', reply)
        self.assertIn('500', reply)

    def test_ai_is_sole_authority_for_site_plan_analysis_and_design(self):
        module = self.application_module
        contract = {
            'projectName': 'Sole Authority Project',
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        program = {
            'buildings': [{'id': 'b1', 'name': 'Tower A', 'footprintArea': 300, 'basementOnly': False}],
            'siteItems': [{'id': 's1', 'name': 'Green Spaces', 'area': 150}],
        }
        data = {
            'message': 'صمم المخطط العام للموقع مع مراعاة ارتدادات الواجهات',
            'plansWorkflow': {'siteAssistant': {}},
        }
        mock_ai_scene = {
            'buildings': [{
                'id': 'b1',
                'name': 'Tower A',
                'footprint': [[5, 5], [25, 5], [25, 20], [5, 20]],
                'floors': 3,
            }],
            'openAreas': [{
                'id': 's1',
                'name': 'Green Spaces',
                'polygon': [[26, 5], [35, 5], [35, 20], [26, 20]],
                'featureType': 'landscape',
            }],
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='sole-authority-sig'), \
                    patch.object(module, '_visual_plan_site_call', return_value=(mock_ai_scene, 120)) as model_call:
                packet, _, _, _ = module._visual_plan_site_packet(data)
                # Verify packet is formed cleanly without geometric math engine failure
                self.assertIn('project', packet)
                self.assertEqual(packet['project']['name'], 'Sole Authority Project')

                # Verify AI design scene executes and produces AI-authored layout
                scene = module._visual_plan_site_ai_design_scene(data, packet, contract, program, context)
                self.assertEqual(len(scene['buildings']), 1)
                self.assertEqual(scene['buildings'][0]['name'], 'Tower A')
                self.assertEqual(len(scene['openAreas']), 1)
                self.assertEqual(scene['openAreas'][0]['name'], 'Green Spaces')
                model_call.assert_called_once()

    def test_croquis_and_land_data_reach_contract_and_conflict_interview(self):
        """Verify all croquis & land data reaches contract, design, and conflict facts without 0 or None."""
        module = self.application_module
        project_data = {
            'project_name': 'Land Croquis Full Test',
            'plot_number_croquis': 'قطعة 542',
            'plan_number': 'مخطط 12/ب',
            'deed_number': 'صك 987654321',
            'deed_date': '1445-06-12',
            'croquis_land_area': '1500',
            'boundary_lengths': 'شمال 50م، جنوب 50م، شرق 30م، غرب 30م',
            'surrounding_streets': 'شارع شمالي عرض 20م، شارع غربي عرض 15م',
            'facades_count': 2,
            'facades_directions': 'شمالية، غربية',
            'allowed_uses': 'سكني وتجاري',
            'regulatory_constraints': 'ارتداد أمامي 4م، جانبي 2م',
            'setbacks': 'شمال 4م، جنوب 2م، شرق 2م، غرب 2م',
            'city': 'الرياض',
            'district': 'الملقا',
            'location_address': 'https://maps.google.com/?q=24.8,46.6',
            'survey_coordinates': [
                {'point': '1', 'eastings': 0, 'northings': 0},
                {'point': '2', 'eastings': 50, 'northings': 0},
                {'point': '3', 'eastings': 50, 'northings': 30},
                {'point': '4', 'eastings': 0, 'northings': 30},
            ],
            'financial_study_model': {
                'components': [
                    {'name': 'مبنى تجاري', 'units': 1, 'unitFootprintArea': 450, 'builtArea': 900, 'floors': 2}
                ]
            }
        }
        data = {
            'projectData': project_data,
            'message': 'طيب هي المساحه المطلوبه كام والمتاحه كام؟',
            'plansWorkflow': {
                'boundary': {'points': project_data['survey_coordinates']},
                'siteAssistant': {},
            }
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            contract, context = module._visual_plan_contract(data)

            # 1. Assert all croquis and land data reached contract & context
            self.assertEqual(contract['plotNumber'], 'قطعة 542')
            self.assertEqual(contract['planNumber'], 'مخطط 12/ب')
            self.assertEqual(contract['deedNumber'], 'صك 987654321')
            self.assertEqual(contract['city'], 'الرياض')
            self.assertEqual(contract['district'], 'الملقا')
            self.assertIn('50م', contract['boundaryLengths'])
            self.assertIn('شارع', contract['surroundingStreets'])
            self.assertEqual(contract['allowedUses'], 'سكني وتجاري')

            # 2. Test conflict interview when setback error occurs
            error = module.visual_plan_geometry.PlanGeometryError('تعارض في الارتدادات', 'PLANS_SETBACK_CONFLICT')
            mock_reply = {
                'reply': 'مساحة الأرض 1,500 م²، وحرم البناء الصافي 1,125 م²، والمساحة المطلوبة للبصمات 450 م².',
                'question': 'كيف تفضل المتابعة؟',
                'choices': ['مراجعة الارتدادات', 'تعديل البصمات'],
            }
            with patch.object(module, '_visual_plan_site_call', return_value=(mock_reply, 80)) as model_call:
                result = module._visual_plan_site_conflict_interview(data, error)
                self.assertTrue(result['success'])
                self.assertIn('1,500', result['reply'])
                # Verify facts passed to user_packet had valid non-zero, non-None numbers
                model_call.assert_called_once()
                call_args = model_call.call_args[0]
                user_packet = json.loads(call_args[1])
                facts = user_packet.get('setbackConflict') or {}
                self.assertIsNotNone(facts.get('buildableAreaSqm'))
                self.assertGreater(facts.get('buildableAreaSqm'), 0)
                self.assertIsNotNone(facts.get('requiredFootprintTotalSqm'))
                self.assertGreater(facts.get('requiredFootprintTotalSqm'), 0)
                self.assertEqual(facts.get('plotNumber'), 'قطعة 542')
                self.assertEqual(facts.get('planNumber'), 'مخطط 12/ب')

    def test_argon_is_sole_architect_empowered_to_resolve_conflict_and_generate(self):
        """Argon has full authority to resolve conflicts, answer inquiries,
        and trigger site generation directly without mathematical code-engine veto."""
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
                {'id': 'b1', 'name': 'Main Building', 'footprintArea': 350, 'basementOnly': False},
            ],
            'siteItems': [],
        }
        error = module.visual_plan_geometry.PlanGeometryError(
            'حرم البناء: غير متاح رقمياً بسبب تعارض خطوط الارتداد المسجلة', 'PLANS_SETBACK_CONFLICT')
        data = {
            'message': 'اعتمد التصميم ونفذ المخطط الآن',
            'plansWorkflow': {
                'siteAssistant': {
                    'inputSignature': 'setback-sig',
                    'pendingQuestion': 'كيف تفضل المتابعة؟',
                    'turns': [{'role': 'assistant', 'text': 'كيف تفضل المتابعة؟'}],
                }
            },
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            mock_argon_decision = {
                'ready': True,
                'generateRequested': True,
                'reply': 'قمت بتعديل تموضع المبنى ليتوافق مع الارتدادات النظامية وسأقوم برسم المخطط الآن.',
                'question': '',
                'choices': [],
            }
            generated_result = {
                'success': True,
                'image': '/uploads/creative/test.svg',
                'svgCode': '<svg id="site-plan"></svg>',
                'reply': 'تم إنشاء المخطط بنجاح.',
            }
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value=program), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-sig'), \
                    patch.object(module, '_visual_plan_site_call', return_value=(mock_argon_decision, 120)), \
                    patch.object(module, '_visual_plan_site_generate', return_value=generated_result) as generate_mock:
                result, status = module._visual_plan_site_assistant_execute(data, 'chat')

            self.assertEqual(status, 200)
            self.assertTrue(result['success'])
            generate_mock.assert_called_once()
            self.assertEqual(result['image'], '/uploads/creative/test.svg')

    def test_argon_reply_contains_no_mechanical_error_summary_when_model_answers(self):
        """Mechanical code-engine error summaries must not override or pollute Argon's voice."""
        module = self.application_module
        contract = {
            'landArea': 1000,
            'coverageRatio': 40,
            'setbacks': {'north': 3.0, 'south': 3.0, 'east': 5.0, 'west': 3.0},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'distribution': {'rows': []},
        }
        context = {'components': []}
        error = module.visual_plan_geometry.PlanGeometryError(
            'فشل البحث الهندسي في إيجاد موضع لبصمة المبنى داخل حرم البناء', 'PLANS_SETBACK_CONFLICT')
        data = {
            'message': 'وضح لي المشكلة بالتفصيل',
            'plansWorkflow': {
                'siteAssistant': {
                    'inputSignature': 'setback-sig',
                    'pendingQuestion': 'كيف تفضل المتابعة؟',
                }
            },
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            mock_argon_response = {
                'ready': False,
                'generateRequested': False,
                'reply': 'المشكلة تكمن في أن أبعاد قطعة الأرض مع الارتداد الشرقي 5م تجعل عرض الحرم ضيقًا نسبيًا.',
                'question': 'هل تفضل تقليص عرض بصمة المبنى أم تعديل الارتداد الشرقي؟',
                'choices': ['تقليص عرض البصمة', 'مراجعة الارتداد'],
            }
            with patch.object(module, '_visual_plan_site_packet', side_effect=error), \
                    patch.object(module, '_visual_plan_contract', return_value=(contract, context)), \
                    patch.object(module, '_visual_plan_program', return_value={'buildings': [], 'siteItems': []}), \
                    patch.object(module, '_visual_plan_input_signature', return_value='setback-sig'), \
                    patch.object(module, '_visual_plan_site_call', return_value=(mock_argon_response, 90)):
                result = module._visual_plan_site_conflict_interview(data, error)

            self.assertTrue(result['success'])
            self.assertIn(mock_argon_response['reply'], result['reply'])
            self.assertIn(mock_argon_response['question'], result['reply'])
            self.assertNotIn('فشل البحث الهندسي', result['reply'])





