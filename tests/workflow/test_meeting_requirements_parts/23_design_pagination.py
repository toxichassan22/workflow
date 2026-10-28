class MeetingRequirementsTestsPart23(MeetingRequirementsTests):
    """Location, risk and executive pages must paginate instead of clipping.

    The location reading was sliced past the card capacity and shipped twice
    (one full page plus its own slices). The risk register and the executive
    summary were packed into single dense pages. These checks pin the hard page
    budgets, the slice-only reading, and the export rule that an ungenerated
    entry is skipped rather than rebuilt as a section opener.
    """

    def _branding(self):
        return {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }

    def _cover_index_closing(self):
        return [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]

    def test_site_analysis_page_ranges_stay_under_the_card_budget(self):
        engine = self.application_module.slide_engine
        blocks = ['ب' * 520, 'ب' * 520, 'ب' * 520, 'ب' * 200]
        cap = engine._SITE_ANALYSIS_PAGE_CHARS
        ranges = engine._site_analysis_page_ranges(blocks)
        self.assertGreater(len(ranges), 1)
        for start, end in ranges:
            chunk = blocks[start:(end if end is not None else len(blocks))]
            self.assertLessEqual(sum(len(block) + 1 for block in chunk), cap)

    def test_the_plan_keeps_only_paginated_site_reading_pages(self):
        engine = self.application_module.slide_engine
        long_text = '\n\n'.join(
            'جملة تحليلية رقم %d. %s' % (index, 'تفصيل ' * 60)
            for index in range(6))
        project = {'project_name': 'مشروع الاختبار', 'site_analysis': long_text}
        plan = engine.normalize_presentation_plan(
            {'slides': self._cover_index_closing()}, project_data=project)
        sources = [
            str(item.get('content_source') or '')
            for item in plan['slides']
            if item.get('section_key') == 'location'
        ]
        self.assertTrue(sources)
        self.assertNotIn('site_analysis', sources)
        reading_sources = [source for source in sources if 'site_analysis' in source]
        self.assertGreaterEqual(len(reading_sources), 2)
        self.assertTrue(all(source.startswith('site_analysis:') for source in reading_sources))

    def test_renumber_drops_the_full_reading_page_when_slices_exist(self):
        engine = self.application_module.slide_engine
        body = '<div class="slide"><p>' + ('نص القراءة ' * 60) + '</p></div>'
        slides = self._cover_index_closing()
        slides = [
            slides[0], slides[1],
            {'title': 'ملخص الموقع الجغرافي', 'type': 'content', 'section_key': 'location',
             'content_source': 'site_analysis', 'is_custom': True, 'html': body},
            {'title': 'ملخص الموقع الجغرافي', 'type': 'content', 'section_key': 'location',
             'content_source': 'site_analysis:0:2', 'is_custom': True, 'html': body},
            {'title': 'ملخص الموقع الجغرافي', 'type': 'content', 'section_key': 'location',
             'content_source': 'site_analysis:2:', 'is_custom': True, 'html': body},
            slides[2],
        ]
        renumbered = engine.renumber_presentation_slides(
            slides, branding=self._branding(), project_data={'project_name': 'مشروع'})
        sources = [
            str(item.get('content_source') or '')
            for item in renumbered
            if item.get('section_key') == 'location'
        ]
        self.assertNotIn('site_analysis', sources)
        self.assertIn('site_analysis:0:2', sources)
        self.assertIn('site_analysis:2:', sources)

    def test_export_skips_ungenerated_entries_instead_of_rebuilding_dividers(self):
        app = self.application_module
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'الغلاف', 'type': 'cover', 'section_key': 'cover', 'html': '   '},
            {'title': 'تحليل السوق', 'type': 'content', 'section_key': 'market',
             'content_source': 'market_study_data.summary', 'html': ''},
            {'title': 'محتوى السوق', 'type': 'content', 'section_key': 'market',
             'html': '<div class="slide">محتوى</div>'},
        ]
        kept = app._drop_ungenerated_slides(slides)
        self.assertEqual([item.get('title') for item in kept], ['الغلاف', 'محتوى السوق'])

    def test_the_page_count_follows_the_content_in_every_direction(self):
        engine = self.application_module.slide_engine

        # No risks, no site reading, no summary: the sections emit nothing.
        empty_plan = engine.normalize_presentation_plan(
            {'slides': self._cover_index_closing()}, project_data={'project_name': 'مشروع'})
        self.assertFalse([
            item for item in empty_plan['slides']
            if item.get('section_key') == 'swot_risks' and item.get('design_style') == 'risk'
        ])
        self.assertFalse([
            item for item in empty_plan['slides']
            if str(item.get('content_source') or '').startswith('site_analysis')
        ])

        # One risk is one page; ten long risks open as many pages as they need.
        self.assertEqual(
            engine._risk_page_ranges([{'risk': 'خطر', 'mitigation': 'معالجة'}]),
            [(0, None)])
        many_risks = [
            {'risk': 'خطر رقم %d %s' % (index, 'تفصيل ' * 30),
             'mitigation': 'معالجة ' * 20}
            for index in range(10)
        ]
        self.assertGreaterEqual(len(engine._risk_page_ranges(many_risks)), 3)

        # A long executive summary is not capped at two pages either.
        long_summary = '\n\n'.join(
            'القسم %d\n\n%s' % (index, 'شرح ' * 140)
            for index in range(12))
        long_project = {
            'executive_content': json.dumps({'summary': long_summary}, ensure_ascii=False),
        }
        self.assertGreater(len(engine._executive_summary_pages(long_project)), 3)

    def test_two_risks_stay_on_one_page(self):
        engine = self.application_module.slide_engine
        items = [
            {'risk': 'تأخر التراخيص', 'mitigation': 'فريق تراخيص ومتابعة أسبوعية'},
            {'risk': 'ارتفاع تكاليف المواد', 'mitigation': 'تثبيت عقود التوريد مبكرًا'},
        ]
        self.assertEqual(engine._risk_page_ranges(items), [(0, None)])

    def test_a_short_summary_stays_on_one_page(self):
        engine = self.application_module.slide_engine
        summary = 'البيانات الأساسية\n\nملخص قصير للمشروع.\n\nالموقع\n\nموقع استراتيجي في جدة.'
        short_project = {
            'executive_content': json.dumps({'summary': summary}, ensure_ascii=False),
        }
        pages = engine._executive_summary_pages(short_project)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0][1]), 2)

        long_project = {
            'executive_content': json.dumps({'summary': '\n\n'.join(
                'القسم %d\n\n%s' % (index, 'شرح ' * 160) for index in range(6))},
                ensure_ascii=False),
        }
        self.assertGreater(len(engine._executive_summary_pages(long_project)), 1)

    def test_a_short_site_reading_stays_on_one_page(self):
        engine = self.application_module.slide_engine
        short_reading = 'قراءة موجزة للموقع في جدة ضمن نطاق متكامل.'
        blocks = engine._site_analysis_blocks(short_reading)
        self.assertEqual(engine._site_analysis_page_ranges(blocks), [(0, None)])

    def test_the_cover_photo_is_a_persisted_removable_layer(self):
        engine = self.application_module.slide_engine
        cover_html = '<div class="slide" style="width:1280px;height:720px;"><p>غلاف</p></div>'
        base = [
            {'title': 'الغلاف', 'type': 'cover', 'html': cover_html},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        creative = {'cover': '/uploads/creative/t/revisions/cover.png'}
        project = {'project_name': 'مشروع'}
        out = engine.renumber_presentation_slides(
            base, branding=self._branding(), project_data=project,
            creative_images=creative)
        self.assertIn('data-cover-background="1"', out[0]['html'])
        self.assertIn('/uploads/creative/t/revisions/cover.png', out[0]['html'])

        removed = [dict(base[0], coverBackgroundRemoved=True), base[1], base[2]]
        out_removed = engine.renumber_presentation_slides(
            removed, branding=self._branding(), project_data=project,
            creative_images=creative)
        self.assertNotIn('data-cover-background="1"', out_removed[0]['html'])

        with_background = ('<div class="slide" style="background-image:url(\'/x.png\');">'
                           '<p>غلاف</p></div>')
        out_existing = engine.renumber_presentation_slides(
            [dict(base[0], html=with_background), base[1], base[2]],
            branding=self._branding(), project_data=project, creative_images=creative)
        self.assertNotIn('data-cover-background', out_existing[0]['html'])

    def test_a_deleted_divider_background_is_not_planted_again(self):
        engine = self.application_module.slide_engine
        forced = ("background:#ffffff;background-image:url('/old.png')!important;"
                  "background-size:cover!important;background-position:center center!important;"
                  "background-repeat:no-repeat!important;")
        divider_html = ('<div class="slide" style="width:1280px;height:720px;' + forced + '">'
                        '<div>تحليل السوق</div></div>')
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'تحليل السوق', 'type': 'section_divider', 'section_key': 'market',
             'is_custom': True, '_designer_keep_html': True, 'html': divider_html},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        out = engine.renumber_presentation_slides(
            slides, branding=self._branding(),
            project_data={'project_name': 'مشروع'},
            creative_images={'cover': '/uploads/creative/t/cover.png'})
        divider = out[2]
        self.assertNotIn('background-size:cover!important', divider['html'])
        self.assertNotIn('data-section-divider-background', divider['html'])

        with_layer_html = ('<div class="slide" style="width:1280px;height:720px;">'
                           '<div data-section-divider-background="1" style="position:absolute;'
                           'inset:0;background-image:url(\'/old.png\');background-size:cover;'
                           'background-position:center center;"></div>'
                           '<div>تحليل السوق</div></div>')
        out_kept = engine.renumber_presentation_slides(
            [slides[0], slides[1], dict(slides[2], html=with_layer_html), slides[3]],
            branding=self._branding(), project_data={'project_name': 'مشروع'},
            creative_images={'cover': '/uploads/creative/t/cover.png'})
        self.assertIn('data-section-divider-background', out_kept[2]['html'])
        # The divider's own layer is authoritative; a save/export must not
        # rewrite it from the live cover image.
        self.assertIn('/old.png', out_kept[2]['html'])

    def test_the_client_updates_the_cover_layer_instead_of_replanting_it(self):
        client = read_frontend_text()
        self.assertIn('function updateCoverBackgroundHtml', client)
        self.assertIn('coverBackgroundRemoved', client)
        self.assertIn('sectionDividerBackgroundRemoved', client)
        self.assertIn('data-cover-background', client)
        export_source = client.split('async function exportTenantSlides', 1)[1].split(
            'async function deleteTenantPresentation', 1)[0]
        self.assertNotIn('forceSectionDividerBackgroundHtml', export_source)

    def test_exec_badge_text_reads_a_multi_select_value(self):
        engine = self.application_module.slide_engine
        self.assertEqual(engine._exec_badge_text('["سكني","تجاري"]'), 'سكني، تجاري')
        self.assertEqual(engine._exec_badge_text(['سكني', 'فندقي']), 'سكني، فندقي')
        self.assertEqual(engine._exec_badge_text('سكني'), 'سكني')

    def test_exec_page_uses_the_designed_lead_and_topic_cards(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الاختبار', 'city': 'جدة', 'district': 'الأندلس',
            'project_type': '["سكني","تجاري"]',
            'executive_content': json.dumps({
                'summary': 'البيانات الأساسية\n' + ('مشروع سكني وتجاري ' * 12)
                           + '\n\nالموقع\n' + ('موقع استراتيجي ' * 12),
            }, ensure_ascii=False),
        }
        slide = {
            'title': 'الملخص التنفيذي', 'type': 'content',
            'section_key': 'executive_summary', 'design_style': 'editorial',
            'content_source': 'executive_content.summary:0:2',
            'market_row_start': 0, 'market_row_end': 2,
        }
        html = engine._build_executive_summary_slide(
            slide, project, {'primary_color': '#123B6D', 'accent_color': '#C4A35A'})
        self.assertIn('data-exec-lead="1"', html)
        self.assertIn('data-exec-topic="2"', html)
        self.assertIn('نوع المشروع: سكني، تجاري', html)

    def test_a_continuation_exec_page_reads_as_a_continuing_reading(self):
        engine = self.application_module.slide_engine
        block = 'نص معتمد مفصل يغطي هذا القسم بالكامل مع أرقام ومؤشرات. ' * 12
        summary = '\n\n'.join('%s\n\n%s' % (label, block) for label in (
            'البيانات الأساسية', 'الموقع', 'الأرض والاشتراطات',
            'الجدول الزمني', 'الدراسة المالية', 'فريق العمل'))
        project = {
            'project_name': 'مشروع',
            'executive_content': json.dumps({'summary': summary}, ensure_ascii=False),
        }
        pages = engine._executive_summary_pages(project)
        self.assertGreaterEqual(len(pages), 2)
        branding = {'primary_color': '#123B6D', 'accent_color': '#C4A35A'}
        start, rows = pages[1]
        slide = {
            'title': 'الملخص التنفيذي', 'type': 'content',
            'section_key': 'executive_summary', 'design_style': 'editorial',
            'content_source': 'executive_content.summary:%d:%d' % (start, start + len(rows)),
            'market_row_start': start, 'market_row_end': start + len(rows),
        }
        html = engine._build_executive_summary_slide(slide, project, branding)
        self.assertNotIn('data-exec-lead', html)
        self.assertIn('تابع الملخص التنفيذي', html)
        self.assertEqual(html.count('data-exec-topic='), len(rows))

        first_slide = dict(
            slide, content_source='executive_content.summary',
            market_row_start=0, market_row_end=len(pages[0][1]))
        first_html = engine._build_executive_summary_slide(first_slide, project, branding)
        self.assertIn('data-exec-lead', first_html)
        self.assertNotIn('تابع الملخص التنفيذي', first_html)

    def test_exec_pages_hold_at_most_four_topics(self):
        engine = self.application_module.slide_engine
        summary = '\n\n'.join(
            'القسم %d\n%s' % (index, 'شرح ' * 120)
            for index in range(8))
        project = {
            'executive_content': json.dumps({'summary': summary}, ensure_ascii=False),
        }
        pages = engine._executive_summary_pages(project)
        self.assertGreaterEqual(len(pages), 2)
        for _start, rows in pages:
            self.assertLessEqual(len(rows), 4)
