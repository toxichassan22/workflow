class VisualPlanContractTestsPart09(VisualPlanContractBase):
    """The written-notes review is bound to the input signature, and the main
    facade the server resolves during the check is part of that signature: the
    facade decides which setback is the front one, so the contract changes with
    it.

    The site-assistant request used to trim the workflow down to a fixed field
    list that left the resolved facade out. The server then rebuilt a different
    contract, the review no longer matched its signature, and a clean notes
    check read as "incomplete or conflicting" the moment the main-plan chat
    started — the client was told its notes were broken while the inputs had
    simply moved.
    """

    def project_without_frontage(self):
        points = [
            {'point': '1', 'eastings': 500000, 'northings': 2000000},
            {'point': '2', 'eastings': 500040, 'northings': 2000000},
            {'point': '3', 'eastings': 500040, 'northings': 2000030},
            {'point': '4', 'eastings': 500000, 'northings': 2000030},
        ]
        return {
            'project_name': 'Frontage Case', 'city': 'الرياض',
            'project_idea': 'A residential building with a service entrance.',
            'croquis_land_area': 1200, 'approved_financial_area': 1200,
            'approved_floor_count': 3, 'approved_coverage_ratio': 40,
            'approved_floor_area_ratio': 1.5, 'survey_coordinates': points,
            # No main facade and no street — the direction can only come from
            # the server's own resolution, which is what the check mints.
            'land_and_building_summary': 'A residential parcel with a service core.',
            'regulatory_constraints': 'No vehicle entry from the east.',
            'setbacks': '5 m west; 3 m east; 3 m north; 3 m south',
            'directions_table': [
                {'direction': 'west', 'regulation_text': 'Neighboring plot', 'setback': 5},
                {'direction': 'east', 'regulation_text': 'Neighboring plot', 'setback': 3},
                {'direction': 'north', 'regulation_text': 'Neighboring plot', 'setback': 3},
                {'direction': 'south', 'regulation_text': 'Neighboring plot', 'setback': 3},
            ],
            'project_components_data': [
                {'name': 'Residential', 'useType': 'residential', 'units': 12, 'builtArea': 360},
            ],
            'land_documents_analysis': {'parcels': [{
                'regulatory_constraints': 'No vehicle entry from the east.',
                'setbacks': '5 m west; 3 m east; 3 m north; 3 m south',
                'table_floors': 3, 'coverage_ratio': 40,
            }]},
        }

    def workflow_without_frontage(self, project):
        return {
            'verification': {'approved': True},
            'boundary': {'approved': False, 'points': project['survey_coordinates']},
            'distribution': {'approved': True, 'rows': [{
                'id': 'row_1', 'building': 'Main Building', 'floor_range': '1-3',
                'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120,
            }]},
            'distributionNotes': '',
            'clientNotes': 'Keep the courtyard open on the west side.',
        }

    def model_reply(self, system_prompt, user_prompt, **kwargs):
        """The two models this flow calls: the frontage reader and the notes
        auditor. Both answer from the recorded documents only."""
        if 'مستندات أرض' in str(system_prompt):
            body = {'direction': 'south', 'evidence': 'الواجهة الرئيسية على الجنوب.'}
        else:
            body = {'checks': [{'index': 0, 'result': 'مطابق', 'detail': ''}], 'canProceed': True}
        return {'choices': [{'message': {'content': json.dumps(body, ensure_ascii=False)}}]}

    def site_assistant_payload(self, workflow):
        """Exactly the field list the browser keeps for the main-plan chat."""
        keys = ('verification', 'boundary', 'distribution', 'distributionNotes',
                'clientNotes', 'notesReview', 'scene', 'siteAssistant', 'planContext')
        return {key: workflow.get(key) for key in keys if key in workflow}

    def clean_review(self, project, workflow):
        """Run the notes check for real and return the response body."""
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_openrouter_chat',
                          side_effect=self.model_reply):
            response = client.post('/api/visual-concept/plans-notes-check',
                                   headers=self._headers(self.token_a),
                                   json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertTrue(body['notesReview']['verified'])
        self.assertTrue(body['notesReview']['canProceed'])
        return body

    def test_a_clean_notes_check_survives_the_main_plan_chat(self):
        module = self.application_module
        project = self.project_without_frontage()
        workflow = self.workflow_without_frontage(project)
        body = self.clean_review(project, workflow)
        # The check resolved the facade the croquis text never names.
        self.assertEqual(body['primaryFrontage']['direction'], 'south')

        # The browser keeps the resolved facade with the workflow and sends it.
        workflow['planContext'] = {'primary_frontage': body['primaryFrontage']}
        workflow['notesReview'] = body['notesReview']
        payload = self.site_assistant_payload(workflow)

        with patch.object(module, '_visual_plan_site_interview', return_value={
                'success': True, 'needsClarification': True, 'reply': 'سؤال واحد.',
                'assistantState': {}}):
            response = self.app.test_client().post(
                '/api/visual-concept/site-plan-assistant',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'planAssistantAction': 'chat',
                      'projectData': project, 'plansWorkflow': payload})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotEqual(response.get_json().get('error_code'), 'PLANS_NOTES_CHECK_REQUIRED')

    def test_the_same_review_without_the_facade_reads_as_stale_not_as_a_conflict(self):
        module = self.application_module
        project = self.project_without_frontage()
        workflow = self.workflow_without_frontage(project)
        body = self.clean_review(project, workflow)
        workflow['notesReview'] = body['notesReview']
        payload = self.site_assistant_payload(workflow)
        # The facade never travelled: the server rebuilds a different contract.
        self.assertIsNone(payload.get('planContext'))

        with patch.object(module, '_visual_plan_site_interview', return_value={
                'success': True, 'needsClarification': True, 'reply': 'سؤال واحد.',
                'assistantState': {}}):
            response = self.app.test_client().post(
                '/api/visual-concept/site-plan-assistant',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'planAssistantAction': 'chat',
                      'projectData': project, 'plansWorkflow': payload})
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'PLANS_NOTES_CHECK_REQUIRED')
        message = response.get_json()['error']
        self.assertIn('لم يعد صالحًا', message)
        self.assertNotIn('يحتوي تعارضًا', message)

    def test_the_notes_gate_names_each_state_it_refuses(self):
        module = self.application_module
        project = self.project_without_frontage()
        workflow = self.workflow_without_frontage(project)
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            unchecked = module._visual_plan_notes_gate(
                {'projectData': project, 'plansWorkflow': dict(workflow)})
            self.assertFalse(unchecked['cleared'])
            self.assertEqual(unchecked['reason'], 'not_checked')
            self.assertIn('لم يتم فحص الملاحظات', unchecked['message'])

            conflicting = dict(workflow)
            conflicting['notesReview'] = {'verified': True, 'canProceed': False,
                                          'checks': [{'index': 0, 'note': 'x',
                                                      'result': 'متعارض', 'detail': ''}]}
            gate = module._visual_plan_notes_gate(
                {'projectData': project, 'plansWorkflow': conflicting})
            self.assertFalse(gate['cleared'])
            self.assertEqual(gate['reason'], 'conflict')
            self.assertIn('تعارضًا', gate['message'])

    def test_the_resolved_facade_reaches_the_main_plan_prompt(self):
        """The site plan is drawn against the same facade the geometry used."""
        module = self.application_module
        project = self.project_without_frontage()
        workflow = self.workflow_without_frontage(project)
        workflow['planContext'] = {'primary_frontage': {
            'direction': 'south', 'status': 'ai_resolved', 'evidence': ['الواجهة على الجنوب.']}}
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            contract = module._visual_plan_site_prompt_contract(project, workflow)
        self.assertEqual(contract['primaryFrontage'], 'south')
