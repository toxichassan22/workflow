class VisualPlanContractTestsPart08(VisualPlanContractBase):
    """The stage that owns the floor distribution: one conversation proposes the
    table, explains it, edits it and checks it."""

    def _distribution_workflow(self, rows=None):
        return {
            'verification': {'approved': True, 'checks': [], 'issues': []},
            'distribution': {'rows': rows if rows is not None else [{
                'id': 'row_1', 'building': 'المبنى أ', 'floor_range': 'أرضي',
                'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120,
            }]},
        }

    def _chat_response(self, payload):
        return {'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}}]}

    def test_the_distribution_chat_edits_the_table_and_keeps_the_memory(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({
            'reply': 'تم نقل السكن إلى الطابق الأول.',
            'action': 'update',
            'rows': [{'building': 'المبنى أ', 'floor_range': '1',
                      'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120}],
            'memory': 'العميل يفضّل السكن في الطابق الأول.',
            'decisions': ['السكن في الطابق الأول'],
        })
        with patch.object(module, 'call_openrouter_chat', return_value=model_reply) as chat_call:
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'حوّل السكن للطابق الأول',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
                'history': [{'role': 'user', 'content': 'السكن في الأرضي غير مناسب'},
                            {'role': 'assistant', 'content': 'نقل السكن للطابق الأول'}],
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        self.assertEqual(body['action'], 'update')
        self.assertEqual(body['rows'][0]['floor_range'], '1')
        self.assertEqual(body['memory'], 'العميل يفضّل السكن في الطابق الأول.')
        self.assertEqual(body['decisions'], ['السكن في الطابق الأول'])
        prompt = chat_call.call_args[0][1]
        # The whole thread travels with the request — the answer builds on it.
        self.assertIn('السكن في الأرضي غير مناسب', prompt)
        self.assertIn('نقل السكن للطابق الأول', prompt)
        self.assertIn('حوّل السكن للطابق الأول', prompt)

    def test_the_distribution_chat_refuses_to_drop_an_approved_component(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({
            'reply': 'استبدلت السكن بمحل تجاري.',
            'action': 'update',
            'rows': [{'building': 'المبنى أ', 'floor_range': 'أرضي',
                      'component': 'Retail', 'units_per_floor': 2, 'floor_area_sqm': 80}],
        })
        with patch.object(module, 'call_openrouter_chat', return_value=model_reply):
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'خلي المحل في الأرضي',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        # The update is refused: the table stays as the client left it.
        self.assertEqual(body['action'], 'explain')
        self.assertEqual(body['rows'][0]['component'], 'Residential')
        self.assertIn('residential', body['reply'].lower())

    def test_the_distribution_chat_keeps_the_table_when_the_model_returns_nothing(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({'reply': 'لم يتغير شيء.', 'action': 'update', 'rows': []})
        with patch.object(module, 'call_openrouter_chat', return_value=model_reply):
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'غيّر شيء',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        self.assertEqual(body['action'], 'explain')
        self.assertEqual(body['rows'][0]['component'], 'Residential')

    def test_the_distribution_chat_needs_the_verification_approval(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
            'message': 'اقترح توزيعًا',
            'projectData': self.project(),
            'plansWorkflow': {'verification': {'approved': False}, 'distribution': {'rows': []}},
        })
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.get_json()['error_code'], 'PLANS_VERIFICATION_REQUIRED')

    def test_the_distribution_model_runs_on_the_slide_model_at_maximum_effort(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({'reply': 'تمام.', 'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat', return_value=model_reply) as chat_call:
            client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اشرح التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        kwargs = chat_call.call_args[1]
        self.assertEqual(kwargs.get('model'), module.VISUAL_PLAN_DISTRIBUTION_MODEL)
        self.assertEqual(kwargs.get('reasoning_effort'), 'max')
        # The distribution model is the slide model unless the owner overrides it.
        self.assertEqual(module.VISUAL_PLAN_DISTRIBUTION_MODEL, module.SLIDE_TEXT_MODEL)
