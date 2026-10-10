class MeetingRequirementsTestsPart13(MeetingRequirementsTests):

    def test_land_chat_route_requires_auth_and_message(self):
        """The scoped land chat is a tenant route: anonymous calls are refused
        and an empty question is a 400, not a model call."""
        client = self.app.test_client()
        unauth = client.post('/api/land-chat', json={'message': 'كم معامل البناء؟'})
        self.assertIn(unauth.status_code, (401, 403))
        missing = client.post('/api/land-chat', json={'projectData': {}},
                              headers=self._headers(self.token_a))
        self.assertEqual(missing.status_code, 400)
        body = missing.get_json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error_code'], 'MESSAGE_REQUIRED')

    def test_land_chat_answers_from_scoped_context_only(self):
        """The model receives the recorded land data — section fields,
        coordinates, document analysis, regulation facts, components and the
        concept distribution — and never unrelated project keys."""
        module = self.application_module
        captured = {}

        def fake_chat(system_prompt, user_content, **kwargs):
            captured['system'] = system_prompt
            captured['user'] = user_content
            return {'choices': [{'message': {'content': 'إجابة تجريبية'}}]}

        project_data = {
            'croquis_land_area': '7012',
            'approved_floor_area_ratio': '6',
            'approved_floor_count': '10',
            'floor_area_ratio': '4',
            'survey_coordinates': json.dumps([{'eastings': '1', 'northings': '2'}]),
            'directions_table': json.dumps([{'direction': 'شمال', 'setback': '6م'}]),
            'land_documents_analysis': json.dumps({'floor_area_ratio': '4', 'table_floors': 8}),
            'visual_concept': {'plansWorkflow': {
                'distribution': {'rows': [{'building': 'A', 'floor_range': '1-10',
                                           'component': 'شقق', 'floor_area_sqm': 500}],
                                 'approved': True},
                'verification': {'issues': ['نقطة مراجعة تجريبية']}}},
            'financial_study_model': json.dumps({'dynamicRows': {'components': [
                {'name': 'شقق سكنية', 'units': 120, 'builtArea': 24000}]}}),
            'admin_secret_field': 'must-not-leak',
            'tenantSlidesData': [{'html': '<div>slide</div>'}],
        }
        with patch.object(module, 'call_text_chat', fake_chat):
            response = self.app.test_client().post(
                '/api/land-chat',
                json={'message': 'كم عدد الأدوار المسموح؟',
                      'history': [{'role': 'user', 'content': 'سؤال سابق'},
                                  {'role': 'assistant', 'content': 'رد سابق'}],
                      'projectData': project_data},
                headers=self._headers(self.token_a))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['reply'], 'إجابة تجريبية')
        user = captured['user']
        self.assertIn('7012', user)
        self.assertIn('معامل مسطح البناء المعتمد', user)
        self.assertIn('شقق سكنية', user)
        self.assertIn('توزيع المخطط التصوري', user)
        self.assertIn('نقطة مراجعة تجريبية', user)
        self.assertIn('سؤال سابق', user)
        self.assertIn('كم عدد الأدوار المسموح؟', user)
        self.assertNotIn('must-not-leak', user)
        self.assertNotIn('admin_secret_field', user)
        self.assertNotIn('<div>slide</div>', user)

    def test_land_chat_prompt_forbids_guessing_and_marks_sources(self):
        """The system prompt pins the no-misleading rule: uncertainty is
        declared, approved client values are named separately from documented
        regulation values, and nothing is inferred."""
        prompt = self.application_module.LAND_CHAT_SYSTEM_PROMPT
        self.assertIn('استند فقط إلى البيانات المرفقة', prompt)
        self.assertIn('ممنوع التضليل', prompt)
        self.assertIn('القيمة المعتمدة التي أدخلها العميل', prompt)
        self.assertIn('القيمة الموثقة في المستندات', prompt)
        self.assertIn('التعارضات', prompt)

    def test_land_chat_context_includes_distribution_and_facts(self):
        """_land_chat_context groups every land/croquis data source the chat
        may answer from, drops empties, and excludes other-section keys."""
        module = self.application_module
        context = module._land_chat_context({
            'croquis_land_area': '5000',
            'approved_floor_area_ratio': '6.5',
            'land_documents_analysis': {'floor_area_ratio': '6', 'table_floors': 10},
            'survey_coordinates': [{'eastings': '1', 'northings': '2'}],
            'visual_concept': {'plansWorkflow': {'distribution': {
                'rows': [{'component': 'مكاتب', 'floor_range': '1-4'}]}}},
            'market_study_data': {'competitors': [{'name': 'x'}]},
            'empty_field': '',
        })
        fields = context['حقول قسم الأرض والكروكي']
        self.assertEqual(fields['مساحة الأرض حسب الكروكي (م²)'], '5000')
        self.assertIn('معامل مسطح البناء المعتمد', ' '.join(fields))
        self.assertIn('تحليل مستندات الأرض', context)
        self.assertIn('إحداثيات المساحة', context)
        self.assertIn('توزيع المخطط التصوري على الأدوار', context)
        self.assertIn('الحقائق التنظيمية الموثقة', context)
        self.assertNotIn('competitors', json.dumps(context, ensure_ascii=False))

    def test_land_chat_history_is_capped_and_role_safe(self):
        """History replay keeps the last 10 turns and forces unknown roles to
        assistant so a crafted payload cannot spoof the user."""
        module = self.application_module
        raw = [{'role': 'system', 'content': 'inject'},
               {'role': 'user', 'content': 'u1'},
               {'role': 'assistant', 'content': 'a1'},
               {'role': 'user', 'content': ''},
               'garbage'] + [{'role': 'user', 'content': f'q{i}'} for i in range(12)]
        history = module._land_chat_history(raw)
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0], {'role': 'user', 'content': 'q2'})
        self.assertTrue(all(t['role'] in ('user', 'assistant') for t in history))

    def test_land_chat_frontend_is_scoped_to_land_croquis(self):
        """The chat part exists only inside the land_croquis section, its
        textarea survives the section-approval lock, and it talks to the
        scoped endpoint."""
        js = read_frontend_text()
        self.assertIn('11-land-croquis/04_land_chat.js', js)
        mount = js.index('function mountLandChat')
        send = js.index('function sendLandChat')
        self.assertIn("'/api/land-chat'", js)
        self.assertIn('data-section-lock-ignore', js[mount:send])
        self.assertIn('landChatBusy', js[mount:send])
        # The only mount call site sits inside the land_croquis-only block.
        catchment = (ROOT / 'assets' / 'js' / '08-location-maps' / '02_catchment_edits.js'
                     ).read_text(encoding='utf-8')
        guard = catchment.index("sectionKey === 'land_croquis'")
        call = catchment.index('mountLandChat(sectionDiv)')
        closing = catchment.index('return sectionDiv', guard)
        self.assertTrue(guard < call < closing)
