class MeetingRequirementsTestsPart11(MeetingRequirementsTests):
    def test_renumber_strips_stray_counter_chrome_from_chrome_free_slides(self):
        """Cover/closing/moodboard never receive a managed footer — a counter or
        footer that slipped in through model output must be removed, not kept
        and rewritten with a fresh number (the closing slide's old «10 — 12»
        used to survive renumbering forever)."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        project = {'project_name': 'المشروع'}
        stray = (
            '<footer class="slide-footer" data-slide-footer="1" '
            'style="position:absolute;bottom:0;left:0;right:0;height:36px;">'
            '<span>المشروع</span><span data-slide-counter="1" dir="ltr">10 — 12</span></footer>'
            '<div data-slide-counter="1" dir="ltr" '
            'style="position:absolute;bottom:34px;left:48px;">11 — 12</div>'
            '<div style="position:absolute;bottom:20px;right:48px;">12 — 12</div>'
        )
        slides = [
            {'title': 'الغلاف', 'type': 'cover',
             'html': '<div class="slide">غلاف' + stray + '</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'ملخص المشروع', 'type': 'content', 'section_key': 'overview',
             'html': '<div class="slide">محتوى</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing',
             'html': '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
                     'position:relative;background:#111;color:#fff;"><h2>الخاتمة</h2>'
                     + stray + '</div>'},
        ]
        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        for idx in (0, 3):
            html = renumbered[idx]['html']
            self.assertNotIn('data-slide-counter', html)
            self.assertNotIn('data-slide-footer', html)
            self.assertNotRegex(html, r'>\s*\d{1,3}\s*[—–/-]\s*\d{1,3}\s*<')
        self.assertIn('الخاتمة', renumbered[3]['html'])

        # Content slides are untouched by the strip: their counter updates.
        self.assertIn('03 — 04', renumbered[2]['html'])
        self.assertIn('data-slide-counter="1"', renumbered[2]['html'])

        # Designer-preserved closing slides take the preserved-counter path —
        # the strip must apply there too.
        preserved = [dict(slide, _designer_keep_html=True) for slide in slides]
        renumbered = engine.renumber_presentation_slides(
            preserved, branding=branding, project_data=project)
        for idx in (0, 3):
            html = renumbered[idx]['html']
            self.assertNotIn('data-slide-counter', html)
            self.assertNotIn('data-slide-footer', html)

    def test_postprocess_removes_model_authored_footer_number_from_closing(self):
        """The model sometimes paints a page number on the dark closing slide
        itself. Generation-time post-processing must strip it so the stale
        number never reaches the deck."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        html = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'position:relative;background:#1a1a1a;color:#fff;"><h2>الخاتمة</h2>'
            '<div style="position:absolute;bottom:34px;left:48px;">15 — 15</div>'
            '<span data-slide-counter="1" dir="ltr" '
            'style="position:absolute;bottom:34px;right:48px;">15 — 15</span></div>'
        )
        finished = engine.postprocess_slide(
            html, 'closing', slide_num=15, slide_title='الخاتمة', total_slides=15,
            branding=branding, project_data={'project_name': 'المشروع'})
        self.assertNotIn('data-slide-counter', finished)
        self.assertNotRegex(finished, r'>\s*\d{1,3}\s*[—–/-]\s*\d{1,3}\s*<')
        self.assertIn('الخاتمة', finished)

    def test_frontend_renumber_removes_counter_chrome_on_chrome_free_slides(self):
        """The browser-side renumber must mirror the server: on cover, closing
        and moodboard slides it removes managed counters too, not only footer
        wrappers — otherwise a bare data-slide-counter stays stale on screen."""
        source = read_frontend_text()
        block = source.split('function renumberTenantSlideHtml', 1)[1]
        free_branch = block.split("['cover', 'closing', 'moodboard']", 1)[1]
        free_branch = free_branch.split('} else {', 1)[0]
        self.assertIn('data-slide-counter', free_branch)
