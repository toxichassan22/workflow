class MeetingRequirementsTestsPart08(MeetingRequirementsTests):

    def test_contact_section_and_fields_registered_and_piped(self):
        """Contact information section and its 7 fields are registered in schema and piped to slide engine."""
        import slide_engine

        # Section exists in FIELD_SECTIONS
        contact_sec = next((s for s in db.FIELD_SECTIONS if s['key'] == 'contact'), None)
        self.assertIsNotNone(contact_sec)
        self.assertEqual(contact_sec['label'], 'بيانات التواصل')

        # 7 prebuilt fields exist in PREBUILT_FIELDS
        prebuilt_by_key = {f['key']: f for f in db.PREBUILT_FIELDS}
        expected_keys = [
            'contact_name', 'contact_position', 'contact_email', 'contact_phone',
            'contact_website', 'contact_address', 'contact_social_media'
        ]
        for key in expected_keys:
            self.assertIn(key, prebuilt_by_key)
            self.assertEqual(prebuilt_by_key[key]['section_key'], 'contact')

        # slide_engine._contact_facts formats all 7 fields
        facts = slide_engine._contact_facts({
            'contact_name': 'سعد الأحمد',
            'contact_position': 'المدير التنفيذي',
            'contact_phone': '0500000000',
            'contact_email': 'info@project.sa',
            'contact_website': 'https://project.sa',
            'contact_address': 'الرياض - طريق الملك فهد',
            'contact_social_media': '@project_sa',
        })
        self.assertIn('سعد الأحمد', facts)
        self.assertIn('المدير التنفيذي', facts)
        self.assertIn('0500000000', facts)
        self.assertIn('info@project.sa', facts)
        self.assertIn('https://project.sa', facts)
        self.assertIn('الرياض - طريق الملك فهد', facts)
        self.assertIn('@project_sa', facts)

        # When no contact data is entered, _contact_facts returns empty string
        empty_facts = slide_engine._contact_facts({})
        self.assertEqual(empty_facts, '')

        # Closing slide prompt instructions
        closing_msg = slide_engine.build_slide_user_msg({'type': 'closing', 'title': 'الخاتمة'}, 10, 10, {}, {})
        self.assertIn('اقتصر على شكر موجز واسم المشروع', closing_msg)
        self.assertIn('دون أي بيانات وهمية', closing_msg)
        self.assertIn('استخدم الصورة الرئيسية بوضوح', closing_msg)

        # Form renders contact section at the end of the form and sidebar
        index_source = read_frontend_text()
        self.assertIn("renderFormSection('contact')", index_source)
        exec_pos = index_source.index('addExecutiveContentSection(form);')
        contact_pos = index_source.index("renderFormSection('contact')", exec_pos)
        self.assertGreater(contact_pos, exec_pos)

    def test_empty_sections_are_completely_omitted_from_prompt_and_deck_plan(self):
        """Any section with no real data is completely excluded from prompt facts and deck plan."""
        import slide_engine

        basic_only_draft = {
            'project_name': 'مشروع تجريبي',
            'project_type': 'تجاري',
            'financial_study_model': '{}',
            'market_study_data': '{}',
            'team_selection': '{}',
            'executive_content': '{}',
            'timeline_table_data': '[]',
        }

        # 1. Facts omit all empty sections
        facts = slide_engine.build_project_facts(basic_only_draft)
        self.assertIn('### معلومات أساسية', facts)
        self.assertNotIn('### الدراسة المالية', facts)
        self.assertNotIn('### دراسة السوق', facts)
        self.assertNotIn('### فريق العمل', facts)
        self.assertNotIn('### المحتوى التنفيذي المعتمد', facts)
        self.assertNotIn('### بيانات التواصل المعتمدة للخاتمة', facts)

        # 2. Deck plan omits all empty sections and their dividers
        plan = slide_engine.normalize_presentation_plan({}, project_data=basic_only_draft, images={})
        emitted_sections = {s.get('section_key') for s in plan['slides']}
        self.assertNotIn('financial', emitted_sections)
        self.assertNotIn('team', emitted_sections)
        self.assertNotIn('market', emitted_sections)
        self.assertNotIn('timeline', emitted_sections)
        self.assertNotIn('swot_risks', emitted_sections)
        self.assertNotIn('plans', emitted_sections)
        self.assertNotIn('exterior', emitted_sections)
        self.assertNotIn('interior', emitted_sections)
        self.assertNotIn('executive_summary', emitted_sections)

        # 3. Index slide entries match only emitted sections
        index_slide = next(s for s in plan['slides'] if s.get('type') == 'index')
        index_titles = [e['title'] for e in index_slide.get('index_entries', [])]
        self.assertNotIn('الدراسة المالية', index_titles)
        self.assertNotIn('فريق العمل', index_titles)
        self.assertNotIn('تحليل السوق', index_titles)
        self.assertNotIn('الجدول الزمني', index_titles)
        self.assertIn('الخاتمة', index_titles)

    def test_project_facts_drop_stored_chat_run_state_and_frozen_snapshots(self):
        """Working state stored on the draft is bookkeeping, and frozen drift-check
        copies inside a blob are not facts — both used to reach the prompt as if
        they were current data («الأدوار 10» next to the live «12»)."""
        import slide_engine

        draft = {
            'project_name': 'مشروع تجريبي',
            'floorCount': 12,
            'designerChat': {'messages': [{'content': 'STALE_SENTINEL'}]},
            'designerChatSessions': {'s1': {'memory': 'STALE_SENTINEL'}},
            'chatHistory': [{'content': 'STALE_SENTINEL'}],
            'best_use_chat': {'messages': ['STALE_SENTINEL']},
            'draftHistory': [{'change': 'STALE_SENTINEL'}],
            'tenantArchiveCache': {'html': 'STALE_SENTINEL'},
            'slide_generation_checkpoint': {'note': 'STALE_SENTINEL'},
            'slidesData': [{'html': 'STALE_SENTINEL'}],
            'custom_block': {'title': 'التوزيع',
                             'items': [{'name': 'شقق'}],
                             'sourceSnapshot': {'approved_floor_count': 'STALE_SENTINEL'},
                             'sourceHash': 'STALE_SENTINEL',
                             'nested': {'parkingSnapshot': {'x': 'STALE_SENTINEL'},
                                        'keep': 'REAL'}},
        }
        facts = slide_engine.build_project_facts(draft)
        self.assertIn('مشروع تجريبي', facts)
        self.assertIn('التوزيع', facts)
        self.assertIn('شقق', facts)
        self.assertIn('REAL', facts)
        self.assertNotIn('STALE_SENTINEL', facts)
        self.assertNotIn('sourceSnapshot', facts)
        self.assertNotIn('sourceHash', facts)
        self.assertNotIn('parkingSnapshot', facts)

    def test_heatmap_polarity_and_three_tier_colors(self):
        engine = self.application_module.slide_engine
        sample_rows = [
            {
                'السيناريو': 'متحفظ',
                'إجمالي الإيرادات': '125,000,000',
                'إجمالي تكلفة المشروع': '110,000,000',
                'صافي الربح': '15,000,000',
                'ROI كامل الدورة': '13.6%',
                'Project IRR كامل الدورة': '11.2%',
                'Equity IRR كامل الدورة': '14.0%',
                'فترة الاسترداد': '7.2 سنة'
            },
            {
                'السيناريو': 'أساسي',
                'إجمالي الإيرادات': '150,000,000',
                'إجمالي تكلفة المشروع': '105,000,000',
                'صافي الربح': '45,000,000',
                'ROI كامل الدورة': '42.8%',
                'Project IRR كامل الدورة': '16.5%',
                'Equity IRR كامل الدورة': '21.0%',
                'فترة الاسترداد': '5.0 سنة'
            },
            {
                'السيناريو': 'متفائل',
                'إجمالي الإيرادات': '180,000,000',
                'إجمالي تكلفة المشروع': '100,000,000',
                'صافي الربح': '80,000,000',
                'ROI كامل الدورة': '80.0%',
                'Project IRR كامل الدورة': '22.0%',
                'Equity IRR كامل الدورة': '28.5%',
                'فترة الاسترداد': '3.8 سنة'
            }
        ]
        res = engine._extract_heatmap_chart_data({'rows': sample_rows})
        self.assertIn('matrix', res)
        self.assertIn('columns', res)
        self.assertIn('legend', res)
        self.assertIn('html_matrix', res)
        self.assertEqual(len(res['matrix']), 7)

        # 1. Higher is better (Revenue, Profit, ROI, Project IRR, Equity IRR)
        rev = next(r for r in res['matrix'] if r['key'] == 'revenue')
        self.assertTrue(rev['higher_is_better'])
        self.assertEqual(rev['conservative_level'], 'worst')
        self.assertEqual(rev['base_level'], 'medium')
        self.assertEqual(rev['optimistic_level'], 'best')

        # 2. Lower is better (Cost, Payback)
        cost = next(r for r in res['matrix'] if r['key'] == 'cost')
        self.assertFalse(cost['higher_is_better'])
        self.assertEqual(cost['conservative_level'], 'worst')  # 110M is highest cost -> worst
        self.assertEqual(cost['base_level'], 'medium')        # 105M is middle -> medium
        self.assertEqual(cost['optimistic_level'], 'best')    # 100M is lowest cost -> best

        pb = next(r for r in res['matrix'] if r['key'] == 'payback')
        self.assertFalse(pb['higher_is_better'])
        self.assertEqual(pb['conservative_level'], 'worst')   # 7.2 years is longest -> worst
        self.assertEqual(pb['base_level'], 'medium')          # 5.0 years is middle -> medium
        self.assertEqual(pb['optimistic_level'], 'best')      # 3.8 years is shortest -> best

        # 3. Reverse cost scenario where conservative spends less
        reverse_rows = [
            {'السيناريو': 'متحفظ', 'إجمالي تكلفة المشروع': '80,000,000'},
            {'السيناريو': 'أساسي', 'إجمالي تكلفة المشروع': '100,000,000'},
            {'السيناريو': 'متفائل', 'إجمالي تكلفة المشروع': '120,000,000'},
        ]
        rev_res = engine._extract_heatmap_chart_data({'rows': reverse_rows})
        rev_cost = next(r for r in rev_res['matrix'] if r['key'] == 'cost')
        self.assertEqual(rev_cost['conservative_level'], 'best')   # 80M is lowest -> best
        self.assertEqual(rev_cost['base_level'], 'medium')         # 100M is middle -> medium
        self.assertEqual(rev_cost['optimistic_level'], 'worst')    # 120M is highest -> worst

        # 4. Non-numeric payback "لا يسترد"
        non_num_rows = [
            {'السيناريو': 'متحفظ', 'فترة الاسترداد': 'لا يسترد'},
            {'السيناريو': 'أساسي', 'فترة الاسترداد': '5.0 سنة'},
            {'السيناريو': 'متفائل', 'فترة الاسترداد': '3.8 سنة'},
        ]
        non_num_res = engine._extract_heatmap_chart_data({'rows': non_num_rows})
        non_num_pb = next(r for r in non_num_res['matrix'] if r['key'] == 'payback')
        self.assertEqual(non_num_pb['conservative_level'], 'worst')
        self.assertEqual(non_num_pb['base_level'], 'medium')
        self.assertEqual(non_num_pb['optimistic_level'], 'best')

        # 5. Zero emojis, zero icons in generated html_matrix and labels
        self.assertIsNone(re.search(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]', res['html_matrix']))

    def test_heatmap_slide_keeps_all_financial_metrics_inside_card(self):
        engine = self.application_module.slide_engine
        rows = [
            {'السيناريو': 'متحفظ', 'إجمالي الإيرادات': '125,000,000', 'إجمالي تكلفة المشروع': '110,000,000',
             'صافي الربح': '15,000,000', 'ROI كامل الدورة': '13.6%', 'Project IRR كامل الدورة': '11.2%',
             'Equity IRR كامل الدورة': '14.0%', 'فترة الاسترداد': '7.2 سنة'},
            {'السيناريو': 'أساسي', 'إجمالي الإيرادات': '150,000,000', 'إجمالي تكلفة المشروع': '105,000,000',
             'صافي الربح': '45,000,000', 'ROI كامل الدورة': '42.8%', 'Project IRR كامل الدورة': '16.5%',
             'Equity IRR كامل الدورة': '21.0%', 'فترة الاسترداد': '5.0 سنة'},
            {'السيناريو': 'متفائل', 'إجمالي الإيرادات': '180,000,000', 'إجمالي تكلفة المشروع': '100,000,000',
             'صافي الربح': '80,000,000', 'ROI كامل الدورة': '80.0%', 'Project IRR كامل الدورة': '22.0%',
             'Equity IRR كامل الدورة': '28.5%', 'فترة الاسترداد': '3.8 سنة'},
        ]
        slide_html = engine._build_sol_heatmap_slide(
            {'title': 'مقارنة السيناريوهات المالية', 'chart_type': 'heatmap'},
            {'project_name': 'مشروع الاختبار', 'financial_study_model': {'tables': {'sensitivityTable': rows}}},
            {},
        )

        self.assertEqual(slide_html.count('<tr>'), 8)  # header plus all seven metric rows
        for metric in ('إجمالي الإيرادات', 'إجمالي تكلفة المشروع', 'صافي الربح', 'ROI', 'Project IRR', 'Equity IRR', 'فترة الاسترداد'):
            self.assertIn(metric, slide_html)
        self.assertNotIn('max-height:440px;overflow:hidden;', slide_html)
        self.assertIn('max-height:510px;overflow:visible;', slide_html)
