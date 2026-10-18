class VisualPlanContractTestsPart05(VisualPlanContractBase):
    def test_json_empty_component_table_overrides_stale_financial_snapshots(self):
        module = self.application_module
        old_rows = [{'id': 'deleted-villa', 'name': 'فلل محذوفة', 'builtArea': 12000}]
        project = {
            'project_components_data': '[]',
            'financial_study_model': json.dumps({
                'dynamicRows': {'components': old_rows},
                'components': old_rows,
                'financialCalcData': {'components': old_rows},
                'tables': {'componentsTable': old_rows},
            }),
            'financial_calc_data': json.dumps({'components': old_rows}),
            'visual_concept': {'slots': {'plan_site': {
                'svgCode': '<svg>فلل محذوفة</svg>',
                'chat': [{'role': 'assistant', 'text': 'الفلل القديمة مسجلة.'}],
            }}},
        }
        workflow = {
            'distribution': {'rows': [{'component': 'فلل محذوفة', 'notes': 'ملاحظة محفوظة للمراجعة'}]},
            'distributionNotes': 'مراجعة الملاحظة المسجلة في التوزيع.',
        }
        data = {'projectData': project, 'plansWorkflow': workflow}

        with module.app.test_request_context('/'):
            module.g.tenant_id = self.tenant_a
            packet, _contract, _context, _signature = module._visual_plan_site_packet(data)

        self.assertEqual(packet['financialComponents'], [])
        self.assertEqual(packet['landAndRegulations']['financialComponents'], [])
        self.assertNotIn('sourceProjectData', packet)
        self.assertNotIn('sourceDistribution', packet)
        self.assertNotIn('sourceBoundary', packet)
        self.assertEqual(packet['distributionRows'][0]['notes'], 'ملاحظة محفوظة للمراجعة')
        self.assertEqual(packet['distributionNotes'], 'مراجعة الملاحظة المسجلة في التوزيع.')

    def test_legacy_site_chat_without_an_input_signature_discards_old_memory(self):
        module = self.application_module

        state = module._visual_plan_site_state({'plansWorkflow': {'siteAssistant': {
            'summary': 'مكونات قديمة محذوفة من المشروع.',
            'turns': [{'role': 'assistant', 'text': 'المبنى القديم مسجل بمساحة 12,000 م².'}],
            'answers': [{'question': 'ما المساحة؟', 'answer': '12,000 م²'}],
        }}}, 'current-input-signature')

        self.assertEqual(state['summary'], '')
        self.assertEqual(state['turns'], [])
        self.assertEqual(state['answers'], [])

    def test_edit_from_an_old_render_revision_rebases_to_the_current_chat(self):
        module = self.application_module
        project = {'project_components_data': '[]', 'financial_study_model': {
            'dynamicRows': {'components': [{'id': 'deleted-villa', 'name': 'فلل محذوفة'}]},
        }}
        workflow = {'siteAssistant': {
            'inputSignature': 'old-input', 'renderRevision': 4,
            'summary': 'ذاكرة إصدار قديم عن فلل محذوفة.',
            'turns': [{'role': 'assistant', 'text': 'الفلل القديمة مسجلة.'}],
        }, 'scene': {'version': 1, 'inputSignature': 'old-input', 'buildings': []}}
        data = {'projectData': project, 'plansWorkflow': workflow,
                'planAssistantAction': 'edit', 'message': 'راجع المكونات الحالية.',
                'siteSvgCode': '<svg>فلل محذوفة</svg>'}
        model_reply = {'ready': False, 'reply': 'أراجع مكونات المشروع الحالية.',
                       'question': 'هل توجد مكونات حالية تريد إضافتها؟', 'choices': []}

        with module.app.test_request_context('/'):
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_edit', side_effect=AssertionError(
                    'A stale render must be rebased through the current chat')), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 30)) as model_call:
                result, status = module._visual_plan_site_assistant_execute(data, 'edit')

        self.assertEqual(status, 200)
        self.assertTrue(result['contextChanged'])
        self.assertEqual(result['question'], model_reply['question'])
        sent = json.loads(model_call.call_args.args[1])
        self.assertEqual(sent['validatedProjectData']['financialComponents'], [])
        self.assertNotIn('deleted-villa', json.dumps(sent['validatedProjectData'], ensure_ascii=False))
        self.assertNotIn('ذاكرة إصدار قديم', sent['sessionMemory'])
        self.assertNotIn('الفلل القديمة', json.dumps(sent['recentTurns'], ensure_ascii=False))

    def test_changing_assistant_cache_does_not_change_site_input_signature(self):
        module = self.application_module
        project = {'project_name': 'Current project', 'visual_concept': {
            'slots': {'plan_site': {'svgCode': '<svg>old</svg>',
                                    'chat': [{'role': 'assistant', 'text': 'old turn'}]}},
        }}
        first = {'projectData': project, 'plansWorkflow': {'siteAssistant': {'turns': []}}}
        second = {'projectData': {
            **project,
            'visual_concept': {'slots': {'plan_site': {
                'svgCode': '<svg>new</svg>',
                'chat': [{'role': 'assistant', 'text': 'new turn'}],
            }}},
        }, 'plansWorkflow': {'siteAssistant': {'turns': [{'role': 'assistant', 'text': 'new turn'}]}}}

        self.assertEqual(module._visual_plan_site_context_signature(first),
                         module._visual_plan_site_context_signature(second))

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
