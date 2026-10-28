class MeetingRequirementsTestsPart22(MeetingRequirementsTests):
    """Divider classification and duplicate timeline pages are repaired in place.

    Renumbering used to classify any market/swot slide whose title matched the
    section name as a legacy divider. Model-composed pages titled «تحليل السوق»
    were therefore retyped, rebuilt as dividers on export, and given the cover
    photo even though their content was real. The title check now only matches a
    page that carries a divider's short text, and decks already saved with the
    wrong type are restored on the next renumber instead of being regenerated.
    """

    def _branding(self):
        return {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }

    def _market_body(self):
        return ' '.join(f'بند رقم {index} في تحليل السوق' for index in range(80))

    def _deck(self, market_slide):
        return [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            market_slide,
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]

    def test_market_content_titled_like_its_section_is_not_retyped(self):
        engine = self.application_module.slide_engine
        market = {
            'title': 'تحليل السوق', 'type': 'content', 'section_key': 'market',
            'content_source': 'market_study_data.summary',
            'is_custom': True, '_designer_keep_html': True,
            'html': f'<div class="slide" style="background:#ffffff;"><p>{self._market_body()}</p></div>',
        }
        renumbered = engine.renumber_presentation_slides(
            self._deck(market), branding=self._branding(),
            project_data={'project_name': 'مشروع'})
        restored = next(slide for slide in renumbered if slide.get('section_key') == 'market')
        self.assertEqual(restored['type'], 'content')
        self.assertNotEqual(restored.get('design_style'), 'divider')
        self.assertIn('بند رقم 79', restored['html'])

    def test_stuck_market_divider_with_real_content_and_forced_photo_is_restored(self):
        engine = self.application_module.slide_engine
        forced = (
            "background:#ffffff;"
            "background-image:url('/uploads/creative/t/revisions/abc.png')!important;"
            "background-size:cover!important;background-position:center center!important;"
            "background-repeat:no-repeat!important;"
        )
        market = {
            'title': 'تحليل السوق', 'type': 'section_divider', 'section_key': 'market',
            'design_style': 'divider', 'content_source': 'market_study_data.summary',
            'is_custom': True, '_designer_keep_html': True,
            'html': f'<div class="slide" style="{forced}"><p>{self._market_body()}</p></div>',
        }
        renumbered = engine.renumber_presentation_slides(
            self._deck(market), branding=self._branding(),
            project_data={'project_name': 'مشروع'})
        restored = next(slide for slide in renumbered if slide.get('section_key') == 'market')
        self.assertEqual(restored['type'], 'content')
        self.assertNotIn('design_style', restored)
        self.assertNotIn('background-size:cover!important', restored['html'])
        self.assertNotIn('abc.png', restored['html'])
        self.assertIn('بند رقم 79', restored['html'])

    def test_a_real_market_divider_stays_a_divider(self):
        engine = self.application_module.slide_engine
        divider_html = engine.build_section_divider_slide(
            {'title': 'تحليل السوق'}, 3, 4, self._branding(),
            {'project_name': 'مشروع'})
        market = {
            'title': 'تحليل السوق', 'type': 'section_divider', 'section_key': 'market',
            'html': divider_html,
        }
        renumbered = engine.renumber_presentation_slides(
            self._deck(market), branding=self._branding(),
            project_data={'project_name': 'مشروع'})
        divider = next(slide for slide in renumbered if slide.get('section_key') == 'market')
        self.assertEqual(divider['type'], 'section_divider')

    def test_duplicate_timeline_gantt_pages_collapse_to_one(self):
        engine = self.application_module.slide_engine
        divider_html = engine.build_section_divider_slide(
            {'title': 'الجدول الزمني'}, 3, 5, self._branding(),
            {'project_name': 'مشروع'})
        gantt = (
            '<div class="slide" dir="rtl">'
            '<div data-timeline-gantt="1"><div data-timeline-bar="1"></div></div>'
            '</div>'
        )
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'الجدول الزمني', 'type': 'section_divider', 'section_key': 'timeline',
             'html': divider_html},
            {'title': 'الجدول الزمني', 'type': 'content', 'section_key': 'timeline',
             'is_custom': True, 'html': gantt},
            {'title': 'الجدول الزمني ومراحل التطوير', 'type': 'content', 'section_key': 'timeline',
             'is_custom': True, 'html': gantt},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        renumbered = engine.renumber_presentation_slides(
            slides, branding=self._branding(), project_data={'project_name': 'مشروع'})
        gantts = [slide for slide in renumbered
                  if 'data-timeline-gantt' in str(slide.get('html') or '')]
        self.assertEqual(len(gantts), 1)
        self.assertEqual(
            [slide['type'] for slide in renumbered if slide.get('section_key') == 'timeline'],
            ['section_divider', 'content'])

    def test_the_client_repairs_stored_market_dividers_and_duplicate_gantts(self):
        client = read_frontend_text()
        self.assertIn('function repairMisclassifiedMarketDivider', client)
        self.assertIn('FORCED_SECTION_BACKGROUND_RE', client)
        self.assertIn('function collapseDuplicateTimelineGantts', client)
        start = client.index('function renumberTenantSlides()')
        head = client[start:start + 400]
        self.assertIn('repairMisclassifiedMarketDivider', head)
        self.assertIn('collapseDuplicateTimelineGantts', head)

    def test_plan_adopts_the_existing_timeline_page_instead_of_adding_another(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع',
            'timeline_start_date': '2030-02-01',
            'timeline_table_data': json.dumps([
                {'name': 'التراخيص', 'start': '2030-02-01', 'end': '2030-06-30'},
            ], ensure_ascii=False),
        }
        plan = {
            'slides': [
                {'title': 'الغلاف', 'type': 'cover'},
                {'title': 'محتويات العرض', 'type': 'index'},
                {'title': 'الجدول الزمني', 'type': 'content',
                 'section_key': 'timeline', 'design_style': 'map'},
                {'title': 'الخاتمة', 'type': 'closing'},
            ],
        }
        normalized = engine.normalize_presentation_plan(plan, project_data=project)
        timeline_content = [
            slide for slide in normalized['slides']
            if slide.get('section_key') == 'timeline' and slide.get('type') == 'content'
        ]
        self.assertEqual(len(timeline_content), 1)
        self.assertEqual(timeline_content[0].get('content_source'), 'timeline_table_data')
        self.assertEqual(timeline_content[0].get('design_style'), 'timeline')
