class MeetingRequirementsTestsPart20(MeetingRequirementsTests):
    """Issue 19 — the sections the model designs, and the ones it must not.

    The renderer used to be decided by the source name alone, so every
    organised source was injected as a static HTML page: the market summary
    shipped as twelve identical rows, the study scope as a dense field list,
    and the risk register as a flat table. The client could only fix it by
    editing the deck by hand.
    """

    def _market_project(self):
        return {
            'project_name': 'مشروع الاختبار',
            'market_study_data': json.dumps({
                'summary': {
                    'market_definition': 'سوق سكني متوسط',
                    'city_position': 'طلب متصاعد',
                    'sector_performance': 'نمو 6%',
                    'supply': 'عرض محدود',
                    'demand': 'طلب مرتفع',
                    'competition': 'منافسة متوسطة',
                    'market_gap': 'فجوة في السكن العائلي',
                    'project_evaluation': 'مشروع جاذب',
                    'recommendation': 'نعم',
                },
                'sources': [
                    {'name': 'هيئة الإحصاء', 'url': 'https://example.com/stats',
                     'note': 'ملاحظة داخلية لا تظهر للعميل',
                     'data_date': '2024-01-01', 'reliability': 'عالية'},
                ],
            }, ensure_ascii=False),
            'executive_content': json.dumps({
                'risks': [{'risk': 'تأخر الروابط', 'mitigation': 'جدول متابعة'}],
            }, ensure_ascii=False),
        }

    def test_the_renderer_policy_names_both_owners(self):
        engine = self.application_module.slide_engine

        # The pages the model composes: a reading, not a table.
        for source, section in (
            ('market_study_data.summary', 'market'),
            ('market_study_data.scope', 'market'),
            ('market_study_data.one_block_summary', 'market'),
            ('executive_content.summary', 'executive_summary'),
            ('executive_content.opportunity', 'executive_summary'),
            ('executive_content.features', 'executive_summary'),
            ('executive_content.risks', 'swot_risks'),
            ('market_study_data.risk_analysis', 'swot_risks'),
        ):
            self.assertEqual(
                engine.slide_content_renderer(
                    {'section_key': section, 'content_source': source}),
                engine.CONTENT_RENDERER_AI, source)

        # The reference pages: the data the client signed off.
        timeline_project = {
            'timeline_start_date': '2030-02-01',
            'timeline_table_data': json.dumps([
                {'name': 'التراخيص', 'start': '2030-02-01', 'end': '2030-06-30'},
            ], ensure_ascii=False),
        }
        for source, section, extra, project in (
            ('market_study_data.competitors', 'market', {'chart_type': 'horizontal_bar'}, None),
            ('market_study_data.sources', 'market', {}, None),
            ('market_study_data.swot', 'market', {}, None),
            ('financial_report:0:0:1', 'financial', {}, None),
            ('timeline_table_data', 'timeline', {}, timeline_project),
            ('land_boundary_diagram', 'land', {}, None),
        ):
            slide = {'section_key': section, 'content_source': source}
            slide.update(extra)
            self.assertEqual(
                engine.slide_content_renderer(slide, project),
                engine.CONTENT_RENDERER_DETERMINISTIC, source)

    def test_the_market_summary_reaches_the_model_instead_of_being_injected(self):
        engine = self.application_module.slide_engine
        project = self._market_project()
        captured = []

        def fake_chat(system, user_msg, **kwargs):
            captured.append(user_msg)
            return {'choices': [{'message': {
                'content': '<div class="slide" dir="rtl"><h2>تحليل السوق</h2>'
                           '<p>تركيب تحريري</p></div>'}}]}

        slide = {
            'title': 'ملخص دراسة السوق', 'type': 'content', 'section_key': 'market',
            'design_style': 'editorial', 'content_source': 'market_study_data.summary',
        }
        html = engine.generate_single_slide(
            'sys', slide, 4, 12, {'primary_color': '#0b1f33'}, fake_chat,
            project_data=project)

        # The model was asked, and the approved findings travelled with it.
        self.assertTrue(captured)
        self.assertIn('فجوة في السكن العائلي', captured[0])
        self.assertIn('سوق سكني متوسط', captured[0])
        # The page is the model's own composition, not the injected table.
        self.assertNotIn('data-market-analysis="1"', html)
        self.assertIn('تركيب تحريري', html)

    def test_the_risk_register_reaches_the_model_instead_of_being_injected(self):
        engine = self.application_module.slide_engine
        project = self._market_project()
        captured = []

        def fake_chat(system, user_msg, **kwargs):
            captured.append(user_msg)
            return {'choices': [{'message': {
                'content': '<div class="slide" dir="rtl"><h2>المخاطر</h2>'
                           '<p>سجل مصمم</p></div>'}}]}

        slide = {
            'title': 'تحليل المخاطر وطرق المعالجة', 'type': 'content',
            'section_key': 'swot_risks', 'design_style': 'risk',
            'content_source': 'executive_content.risks',
        }
        engine.generate_single_slide(
            'sys', slide, 9, 12, {'primary_color': '#0b1f33'}, fake_chat,
            project_data=project)
        self.assertTrue(captured)
        self.assertIn('تأخر الروابط', captured[0])

    def test_the_source_register_shows_the_source_and_its_link_only(self):
        engine = self.application_module.slide_engine
        project = self._market_project()
        slide = {
            'title': 'مصادر دراسة السوق', 'type': 'content', 'section_key': 'market',
            'design_style': 'table', 'content_source': 'market_study_data.sources',
        }
        html = engine._build_market_sources_slide(slide, project, {})
        self.assertIn('هيئة الإحصاء', html)
        self.assertIn('https://example.com/stats', html)
        # The operator's note, the access dates and the reliability rating are
        # working fields: they stay on the platform screen.
        self.assertNotIn('ملاحظة داخلية لا تظهر للعميل', html)
        self.assertNotIn('الملاحظات', html)
        self.assertNotIn('التواريخ والموثوقية', html)

    def test_source_links_are_real_anchors_and_urls_survive_formatting(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الاختبار',
            'market_study_data': json.dumps({'sources': [
                {'name': 'منصة صناعات', 'url': 'https://sna3at.com/posts/14332/'},
                {'name': 'بدون بروتوكول', 'url': 'www.example.com/87958895.html'},
                {'name': 'رابط غير آمن', 'url': 'javascript:alert(1)'},
            ]}, ensure_ascii=False),
        }
        slide = {
            'title': 'مصادر دراسة السوق', 'type': 'content', 'section_key': 'market',
            'design_style': 'table', 'content_source': 'market_study_data.sources',
        }
        html = engine._build_market_sources_slide(slide, project, {})
        # The register used to print every URL as plain text, so the deck had
        # nothing to click and the PDF carried no link annotation at all.
        self.assertIn('<a href="https://sna3at.com/posts/14332/"', html)
        self.assertIn('<a href="https://www.example.com/87958895.html"', html)
        self.assertNotIn('href="javascript:', html)

        finalized = engine.finalize_slide_html(html, 'content', project, {})
        self.assertIn('<a href="https://sna3at.com/posts/14332/"', finalized)
        self.assertIn('<a href="https://www.example.com/87958895.html"', finalized)
        self.assertNotIn('14,332', finalized)
        self.assertNotIn('87,958,895', finalized)

    def test_a_long_market_summary_becomes_several_pages(self):
        engine = self.application_module.slide_engine
        project = self._market_project()
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'ملخص دراسة السوق', 'type': 'content', 'section_key': 'market',
             'content_source': 'market_study_data.summary'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        pages = [slide for slide in plan['slides']
                 if str(slide.get('content_source') or '').startswith('market_study_data.summary')]
        self.assertGreater(len(pages), 1, pages)
        # Every page carries its own slice of the approved findings.
        self.assertTrue(all(slide.get('market_row_start') is not None for slide in pages))
        starts = [slide.get('market_row_start') for slide in pages]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(starts[0], 0)

    def test_the_timeline_is_one_page_in_the_normalized_plan(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الاختبار',
            'timeline_start_date': '2030-02-01',
            'timeline_table_data': json.dumps([
                {'name': 'التراخيص', 'start': '2030-02-01', 'end': '2030-06-30'},
                {'name': 'الهيكل الإنشائي', 'start': '2030-05-01', 'end': '2031-02-28'},
            ], ensure_ascii=False),
        }
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            # A planner that proposed its own timeline page.
            {'title': 'الجدول الزمني ومراحل التطوير', 'type': 'content',
             'section_key': 'timeline', 'design_style': 'timeline',
             'content_source': 'timeline_table_data'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        timeline_pages = [slide for slide in plan['slides']
                          if slide.get('section_key') == 'timeline'
                          and slide.get('type') not in ('section_divider',)]
        self.assertEqual(len(timeline_pages), 1, timeline_pages)
