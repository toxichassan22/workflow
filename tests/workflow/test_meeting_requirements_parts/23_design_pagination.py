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

    def test_the_client_updates_the_cover_layer_instead_of_replanting_it(self):
        client = read_frontend_text()
        self.assertIn('function updateCoverBackgroundHtml', client)
        self.assertIn('coverBackgroundRemoved', client)
        self.assertIn('data-cover-background', client)

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
