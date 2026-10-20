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
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as chat_call:
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
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply):
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
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply):
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
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as chat_call:
            client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اشرح التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        kwargs = chat_call.call_args[1]
        self.assertEqual(kwargs.get('model'), module.VISUAL_PLAN_DISTRIBUTION_MODEL)
        # The owner asked for the same model and the same effort the plan
        # generation uses: sol 6.1 at maximum effort.
        self.assertEqual(kwargs.get('reasoning_effort'), 'max')
        # The same token ceiling as the plan generation: a bigger cap only
        # makes the answer longer, and the table is small.
        self.assertEqual(kwargs.get('max_tokens'), 66000)
        # The distribution model is the slide model unless the owner overrides it.
        self.assertEqual(module.VISUAL_PLAN_DISTRIBUTION_MODEL, module.SLIDE_TEXT_MODEL)
        self.assertEqual(module.SLIDE_TEXT_MODEL, 'openai/gpt-6.1-sol')

    def test_a_failed_turn_is_named_instead_of_answering_an_empty_success(self):
        """A swallowed provider error used to answer 200 with an empty body, so
        the client could not tell a failed turn from a silent one and the table
        simply never changed. Every failure carries its own name now."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        payload = {'message': 'اقترح توزيعًا', 'projectData': self.project(),
                   'plansWorkflow': self._distribution_workflow()}

        with patch.object(module, 'call_openrouter_chat_stream', side_effect=RuntimeError('boom')):
            raised = client.post('/api/visual-concept/plans-distribution-chat',
                                 headers=headers, json=payload)
        self.assertEqual(raised.status_code, 503, raised.get_json())
        self.assertEqual(raised.get_json()['error_code'], 'PLANS_PROVIDER_FAILED')

        with patch.object(module, 'call_openrouter_chat_stream', return_value={
                'error': {'message': 'انتهت مهلة الاتصال بالمزوّد (300 ثانية)'}}):
            timed_out = client.post('/api/visual-concept/plans-distribution-chat',
                                    headers=headers, json=payload)
        self.assertEqual(timed_out.status_code, 503, timed_out.get_json())
        self.assertEqual(timed_out.get_json()['error_code'], 'PLANS_PROVIDER_TIMEOUT')

        with patch.object(module, 'call_openrouter_chat_stream',
                          return_value={'choices': [{'message': {'content': 'ليس JSON'}}]}):
            unreadable = client.post('/api/visual-concept/plans-distribution-chat',
                                     headers=headers, json=payload)
        self.assertEqual(unreadable.status_code, 503, unreadable.get_json())
        self.assertEqual(unreadable.get_json()['error_code'], 'PLANS_ANSWER_UNREADABLE')

        with patch.object(module, 'call_openrouter_chat_stream', return_value={
                'choices': [{'message': {'content': json.dumps({'action': 'explain'})}}]}):
            empty = client.post('/api/visual-concept/plans-distribution-chat',
                                headers=headers, json=payload)
        self.assertEqual(empty.status_code, 503, empty.get_json())
        self.assertEqual(empty.get_json()['error_code'], 'PLANS_ANSWER_EMPTY')

    def test_the_turn_is_queued_and_answered_off_the_request_path(self):
        """The model thinks for minutes and the hosting proxy drops a request
        that stays open that long, so the turn is a job the browser polls."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        payload = {'message': 'اقترح توزيعًا', 'projectData': self.project(),
                   'plansWorkflow': self._distribution_workflow(), 'background': True}
        with patch.object(module.threading, 'Thread') as thread:
            queued = client.post('/api/visual-concept/plans-distribution-chat',
                                 headers=headers, json=payload)
        self.assertEqual(queued.status_code, 202, queued.get_json())
        job_id = queued.get_json()['jobId']
        pending = client.get('/api/visual-concept/plans-jobs/' + job_id, headers=headers)
        self.assertEqual(pending.get_json()['status'], 'queued')
        # The steps the client shows while it waits.
        self.assertEqual([item['label'] for item in pending.get_json()['todos']],
                         ['قراءة بيانات المشروع والتوزيع', 'اقتراح توزيع الأدوار', 'مراجعة النتيجة'])
        worker = thread.call_args.kwargs
        model_reply = self._chat_response({'reply': 'تم توزيع الأدوار.', 'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply), \
                patch.object(module.auth, '_load_token_user', return_value=(None, None)), \
                patch.object(module.auth, '_session_state_error', return_value=None), \
                patch.object(module, '_landloom_can', return_value=True):
            worker['target'](*worker['args'])
        completed = client.get('/api/visual-concept/plans-jobs/' + job_id, headers=headers)
        self.assertEqual(completed.get_json()['status'], 'completed', completed.get_json())
        self.assertTrue(completed.get_json()['result']['success'])
        self.assertEqual(completed.get_json()['result']['reply'], 'تم توزيع الأدوار.')

    def test_starting_the_distribution_over_ignores_the_current_table_and_the_thread(self):
        """A clean start must not be weighed against the floors and the
        decisions the client asked to drop."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({
            'reply': 'اقتراح جديد من الصفر.',
            'action': 'update',
            'rows': [{'building': 'المبنى ب', 'floor_range': 'أرضي',
                      'component': 'Residential', 'units_per_floor': 2, 'floor_area_sqm': 90}],
        })
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as chat_call:
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'ابدأ من جديد',
                'reset': True,
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
                'history': [{'role': 'user', 'content': 'السكن في الأرضي غير مناسب'}],
                'memory': 'العميل يفضّل السكن في الطابق الأول',
                'decisions': ['السكن في الطابق الأول'],
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        self.assertEqual(body['action'], 'update')
        self.assertEqual(body['rows'][0]['building'], 'المبنى ب')
        self.assertTrue(body['reset'])
        prompt = chat_call.call_args[0][1]
        # The old table and the old thread are gone from the prompt.
        self.assertNotIn('المبنى أ', prompt)
        self.assertNotIn('السكن في الأرضي غير مناسب', prompt)
        self.assertNotIn('العميل يفضّل السكن في الطابق الأول', prompt)
        self.assertIn('بدء التوزيع من جديد', prompt)

    def test_the_provider_call_stays_inside_the_job_deadline(self):
        """The turn is bounded: the provider call gets the remaining time of the
        job, never more than the bound the owner set."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({'reply': 'تمام.', 'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as chat_call:
            client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اشرح التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        # Ten minutes of provider time for the slowest model the product owns.
        self.assertEqual(chat_call.call_args[1].get('timeout'), 600)
        with self.app.test_request_context('/'):
            module.g.visual_plan_job_deadline = module.time.time() + 40
            with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as bounded:
                client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                    'message': 'اشرح التوزيع',
                    'projectData': self.project(),
                    'plansWorkflow': self._distribution_workflow(),
                })
        self.assertLessEqual(bounded.call_args[1].get('timeout'), 40)

    def test_neither_the_request_nor_the_answer_is_cut(self):
        """A long request and a long answer travel whole: a silent cut loses
        the end of what the client wrote."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        long_request = 'السكن في الطابق الثاني. ' * 900
        long_reply = 'تم. ' * 1200
        model_reply = self._chat_response({
            'reply': long_reply, 'action': 'explain',
        })
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply) as chat_call:
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': long_request,
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        # The request reached the model whole.
        prompt = chat_call.call_args[0][1]
        self.assertIn(long_request.strip()[:4000], prompt)
        self.assertIn(long_request.strip()[-400:], prompt)
        # The answer came back whole: the end of it is still there.
        self.assertTrue(body['reply'].endswith('تم.'))
        self.assertGreaterEqual(len(body['reply']), len(long_reply) * 0.9)
        # The stored turn is not cut either.
        self.assertEqual(len(body['memory'] or ''), 0)

    def test_the_turn_that_leaves_the_floors_alone_says_so(self):
        """A finished turn that did not change the table must not look like an
        applied layout — the client says what actually happened."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({'reply': 'السكن في الطابق الأول.', 'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply):
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اشرح التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        body = answer.get_json()
        self.assertEqual(body['action'], 'explain')
        self.assertFalse(body['tableChanged'])
        self.assertEqual(body['rows'][0]['component'], 'Residential')

        with patch.object(module, 'call_openrouter_chat_stream', return_value=self._chat_response({
                'reply': 'تم.', 'action': 'update',
                'rows': [{'building': 'المبنى أ', 'floor_range': '1',
                          'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120}]})):
            applied = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اعتمد التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertTrue(applied.get_json()['tableChanged'])

    def test_the_model_asks_instead_of_guessing(self):
        """A fact the approved data cannot answer is a question, not a guess:
        the chat asks, and the table stays as it was until it is answered."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        model_reply = self._chat_response({
            'reply': 'أين تريد الوحدات التجارية؟',
            'action': 'ask',
            'question': 'أين تريد الوحدات التجارية؟',
            'choices': ['في الأرضي', 'في الطابق الأول'],
        })
        with patch.object(module, 'call_openrouter_chat_stream', return_value=model_reply):
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'وزّع المكونات',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        body = answer.get_json()
        self.assertEqual(body['action'], 'ask')
        self.assertEqual(body['question'], 'أين تريد الوحدات التجارية؟')
        self.assertEqual(body['choices'], ['في الأرضي', 'في الطابق الأول'])
        # The question is not a layout: the floors are untouched.
        self.assertFalse(body['tableChanged'])
        self.assertEqual(body['rows'][0]['component'], 'Residential')

    def test_a_described_layout_is_asked_for_again_as_a_table(self):
        """The model described the layout instead of returning it: the client
        asked for the table, so the server asks once more for the rows. A
        described layout never reaches the floors table on its own."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        described = self._chat_response({
            'reply': 'السكن في الطابق الثاني والتخزين في البدروم.',
            'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat_stream',
                          side_effect=[described, described]) as chat_call:
            plain = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اشرح التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        # A question about the layout is not a request for the layout: the
        # model is not asked twice.
        self.assertEqual(plain.status_code, 200, plain.get_json())
        self.assertEqual(chat_call.call_count, 1)
        self.assertFalse(plain.get_json()['tableChanged'])

        with patch.object(module, 'call_openrouter_chat_stream', side_effect=[
                described,
                self._chat_response({
                    'reply': 'تم.', 'action': 'update',
                    'rows': [{'building': 'المبنى أ', 'floor_range': '2',
                              'component': 'Residential', 'units_per_floor': 4,
                              'floor_area_sqm': 120}]})]) as chat_call:
            applied = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'اعتمد التوزيع',
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(chat_call.call_count, 2)
        # The second call asks for the rows, not for another description.
        self.assertIn('rows', chat_call.call_args_list[1].args[1])
        self.assertTrue(applied.get_json()['tableChanged'])
        self.assertEqual(applied.get_json()['rows'][0]['floor_range'], '2')

    def test_applying_the_described_layout_asks_for_the_same_table(self):
        """«طبّق ما في الشات» is not a new proposal: the model is asked to
        re-send the layout it described, and the retry asks for the same one."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        described = self._chat_response({
            'reply': 'السكن في الطابق الثاني والتخزين في البدروم.',
            'action': 'explain'})
        with patch.object(module, 'call_openrouter_chat_stream', side_effect=[
                described,
                self._chat_response({
                    'reply': 'تم.', 'action': 'update',
                    'rows': [{'building': 'المبنى أ', 'floor_range': '2',
                              'component': 'Residential', 'units_per_floor': 4,
                              'floor_area_sqm': 120}]})]) as chat_call:
            answer = client.post('/api/visual-concept/plans-distribution-chat', headers=headers, json={
                'message': 'طبّق ما في الشات',
                'applyProposal': True,
                'expectTable': True,
                'projectData': self.project(),
                'plansWorkflow': self._distribution_workflow(),
            })
        self.assertEqual(answer.status_code, 200, answer.get_json())
        # The prompt asks for the same layout, not for a new one.
        prompt = chat_call.call_args_list[0].args[1]
        self.assertIn('أعد توزيعك السابق كما هو', prompt)
        self.assertNotIn('اقترح توزيعًا كاملًا', prompt)
        retry_prompt = chat_call.call_args_list[1].args[1]
        self.assertIn('نفس المباني ونفس الأدوار', retry_prompt)
        self.assertTrue(answer.get_json()['tableChanged'])
