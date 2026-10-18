class VisualPlanContractTestsPart06(VisualPlanContractBase):
    def project_inputs(self):
        return {
            'project_name': 'North District Plan',
            'approved_financial_area': '24912.95',
            'croquis_land_area': '1000',
            'survey_coordinates': [
                {'point': '1', 'eastings': 0, 'northings': 0},
                {'point': '2', 'eastings': 40, 'northings': 0},
                {'point': '3', 'eastings': 40, 'northings': 25},
                {'point': '4', 'eastings': 0, 'northings': 25},
            ],
            'financial_study_model': {'components': [{
                'id': 'component-1', 'name': 'Residential Building', 'units': 4,
                'unitFootprintArea': 125, 'notes': 'The eastern wing has a separate entrance.'
            }]},
        }

    def workflow_inputs(self):
        return {
            'distribution': {'rows': [{
                'id': 'floor-row-1', 'building': 'Residential Building',
                'component': 'Apartments', 'floor_range': '1-4',
                'floor_area_sqm': 500, 'units_per_floor': 4,
                'notes': 'Keep the family rooms facing the garden.'
            }]},
            'distributionNotes': 'Place the service core away from the main entrance.',
            'clientNotes': 'Keep a quiet courtyard between the buildings.',
            'siteAssistant': {},
        }

    def test_argon_receives_area_sources_and_all_distribution_notes_on_every_turn(self):
        module = self.application_module
        data = {'projectData': self.project_inputs(),
                'message': 'راجع مساحة الأرض والتوزيع',
                'plansWorkflow': self.workflow_inputs()}
        replies = [
            ({'ready': False, 'question': 'هل مساحة الأرض المعتمدة هي 24912.95 م²؟',
              'choices': [], 'memory': 'Confirm the area source.'}, 90),
            ({'ready': False, 'reply': 'المساحة المعتمدة للدراسة المالية 24912.95 م².',
              'question': 'هل نعتمد هذه القيمة للمخطط؟', 'choices': [],
              'memory': 'The client is confirming the approved area.'}, 70),
        ]

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_scene_from_request', side_effect=AssertionError(
                    'The chat must not validate geometry')), \
                    patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                        'The chat must not build or validate engineering geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'The chat must not calculate a placement program')), \
                    patch.object(module, '_visual_plan_site_call', side_effect=replies) as model_call:
                first, status = module._visual_plan_site_assistant_execute(data, 'chat')
                followup_data = {
                    'projectData': self.project_inputs(),
                    'message': 'أيوه اعتمد المساحة دي',
                    'plansWorkflow': {**self.workflow_inputs(),
                                      'siteAssistant': first['assistantState']},
                }
                followup, followup_status = module._visual_plan_site_assistant_execute(
                    followup_data, 'chat')

        self.assertEqual((status, followup_status), (200, 200))
        self.assertTrue(first['needsClarification'])
        self.assertEqual(followup['assistantState']['answers'][0]['answer'], 'أيوه اعتمد المساحة دي')
        for call in model_call.call_args_list:
            sent = json.loads(call.args[1])
            facts = sent['validatedProjectData']
            self.assertEqual(facts['projectMeasurements']['landAreaSqm'], 24912.95)
            self.assertEqual(facts['projectMeasurements']['croquisLandAreaSqm'], '1000')
            self.assertEqual(facts['distributionRows'][0]['notes'],
                             'Keep the family rooms facing the garden.')
            self.assertEqual(facts['distributionNotes'],
                             'Place the service core away from the main entrance.')
            self.assertEqual(facts['clientNotes'], 'Keep a quiet courtyard between the buildings.')
            self.assertEqual(facts['financialComponents'][0]['unitFootprintArea'], 125)
            self.assertEqual(facts['financialComponents'][0]['notes'],
                             'The eastern wing has a separate entrance.')

    def test_argon_controls_conflict_reply_and_the_renderer_uses_its_coordinates(self):
        module = self.application_module
        contract = {
            'projectName': 'Sole Authority Project', 'landArea': 24912.95,
            'setbacks': {'north': 3, 'south': 3, 'east': 5, 'west': 3},
            'geometry': {'parcels': [{'polygon': [[0, 0], [40, 0], [40, 25], [0, 25]]}]},
            'primaryFrontage': {'direction': 'west'}, 'directions': [],
            'distribution': {'rows': []},
        }
        data = {'projectData': self.project_inputs(), 'plansWorkflow': self.workflow_inputs()}
        packet = {'projectMeasurements': {'landAreaSqm': 24912.95},
                  'distributionRows': self.workflow_inputs()['distribution']['rows'],
                  'distributionNotes': self.workflow_inputs()['distributionNotes'],
                  'clientNotes': self.workflow_inputs()['clientNotes'],
                  'financialComponents': [{'name': 'Residential Building',
                                          'unitFootprintArea': 125}]}
        model_reply = {
            'ready': True, 'conflict': False,
            'buildings': [{'id': 'building-ai', 'name': 'Residential Building',
                           'label': 'Residential Building', 'category': 'residential',
                           'levels': 4,
                           'footprint': [[8, 6], [18, 6], [18, 16], [8, 16]]}],
            'openAreas': [{'id': 'courtyard-ai', 'componentId': 'courtyard-ai',
                           'name': 'Courtyard', 'label': 'Courtyard',
                           'polygon': [[20, 6], [28, 6], [28, 14], [20, 14]],
                           'featureType': 'landscape'}],
            'entries': [{'id': 'entry-ai', 'point': [0, 12], 'entryType': 'main',
                         'label': 'Main Entry'}],
        }

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_call', return_value=(model_reply, 120)) as model_call, \
                    patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                        'Argon placement must not call the engineering contract')):
                scene = module._visual_plan_site_ai_design_scene(
                    data, packet, contract)

        self.assertEqual(scene['buildings'][0]['footprint'], model_reply['buildings'][0]['footprint'])
        self.assertEqual(scene['openAreas'][0]['polygon'], model_reply['openAreas'][0]['polygon'])
        self.assertEqual(scene['entries'][0]['point'], [0, 12])
        self.assertEqual(scene['buildings'][0]['id'], 'building-ai')
        prompt = json.loads(model_call.call_args.args[1])
        self.assertEqual(prompt['projectMeasurements']['landAreaSqm'], 24912.95)
        self.assertEqual(prompt['distributionNotes'], packet['distributionNotes'])
        self.assertIn('calculations, distribution, conflict checks', model_call.call_args.args[0])

    def test_argon_can_return_a_conflict_without_any_engine_placement_or_retry(self):
        module = self.application_module
        decision = {'ready': False, 'conflict': True,
                    'reply': 'بصمات المباني لا تتسع بعد تطبيق الارتدادات المسجلة.',
                    'question': 'هل تريد مراجعة بصمة الدور الأرضي؟',
                    'choices': ['مراجعة بصمة الدور الأرضي']}
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_call', return_value=(decision, 80)), \
                    patch.object(module, '_visual_plan_site_seal_scene', side_effect=AssertionError(
                        'A conflict response must not create a fallback scene')):
                result = module._visual_plan_site_ai_design_scene(
                    {}, {'distributionRows': [], 'projectMeasurements': {}},
                    {'geometry': {'parcels': [{'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]}]}})

        self.assertEqual(result['assistantDecision'], decision)

    def test_site_generation_never_calls_the_program_or_geometry_engine(self):
        module = self.application_module
        project = self.project_inputs()
        workflow = self.workflow_inputs()
        data = {'projectData': project, 'plansWorkflow': workflow}
        signature = module._visual_plan_site_context_signature(data)
        interview = {'success': True, 'readyForGeneration': True, 'needsClarification': False,
                     'assistantState': {'inputSignature': signature, 'readyForGeneration': True,
                                        'generateRequested': True, 'redesignRequested': True,
                                        'status': 'ready', 'checkpoints': {}, 'turns': [],
                                        'answers': [], 'summary': '', 'pendingQuestion': ''}}
        model_layout = {
            'ready': True, 'conflict': False,
            'buildings': [{'id': 'argon-building', 'name': 'Residential Building',
                           'label': 'Residential Building', 'category': 'residential',
                           'footprint': [[0, 0], [10, 0], [10, 10], [0, 10]]}],
            'openAreas': [], 'entries': [],
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            module.g.tenant = {}
            with patch.object(module, '_visual_plan_site_interview', return_value=interview), \
                    patch.object(module, '_visual_plan_site_call', return_value=(model_layout, 100)), \
                    patch.object(module, '_visual_plan_contract', side_effect=AssertionError(
                        'Site chat generation must not calculate or validate project geometry')), \
                    patch.object(module, '_visual_plan_program', side_effect=AssertionError(
                        'Site chat generation must not calculate building distributions')), \
                    patch.object(module, 'persist_generated_image',
                                 return_value='/uploads/creative/site-plan.svg'):
                result, status = module._visual_plan_site_assistant_execute(data, 'generate')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertEqual(result['scene']['buildings'][0]['footprint'],
                         model_layout['buildings'][0]['footprint'])
        self.assertEqual(result['scene']['inputSignature'], signature)

