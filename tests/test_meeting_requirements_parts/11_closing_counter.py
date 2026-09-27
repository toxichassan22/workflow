class MeetingRequirementsTestsPart11(MeetingRequirementsTests):
    def test_renumber_updates_stray_counter_on_closing_slide(self):
        """The closing slide is displayed with its slide number like the rest
        of the deck, so renumbering must update it — a marked counter, an
        unmarked bottom-corner number, and a missing one all end up correct."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        project = {'project_name': 'المشروع'}
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'ملخص المشروع', 'type': 'content', 'section_key': 'overview',
             'html': '<div class="slide">محتوى</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing',
             'html': '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
                     'position:relative;background:#111;color:#fff;"><h2>الخاتمة</h2>'
                     '<div>تواصل: 0500000000</div>'
                     '<div data-slide-counter="1" dir="ltr" '
                     'style="position:absolute;bottom:34px;left:48px;">10 — 12</div></div>'},
        ]
        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        closing_html = renumbered[3]['html']
        self.assertIn('data-slide-counter', closing_html)
        self.assertIn('04 — 04', closing_html)
        self.assertNotIn('10 — 12', closing_html)
        self.assertIn('0500000000', closing_html)
        self.assertIn('الخاتمة', closing_html)

        # An unmarked bottom-corner number is promoted and updated, not left stale.
        slides[3]['html'] = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'position:relative;background:#111;color:#fff;"><h2>الخاتمة</h2>'
            '<div style="position:absolute;bottom:20px;right:48px;">09 — 12</div></div>')
        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        closing_html = renumbered[3]['html']
        self.assertIn('data-slide-counter', closing_html)
        self.assertIn('04 — 04', closing_html)
        self.assertNotIn('09 — 12', closing_html)

        # A closing slide with no number element gets one injected above the
        # brand overlay — without z-index the counter renders under
        # data-cover-overlay (z-index:1) and stays invisible.
        slides[3]['html'] = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'position:relative;background:#111;color:#fff;">'
            '<div data-cover-overlay style="position:absolute;inset:0;z-index:1;"></div>'
            '<h2>الخاتمة</h2></div>')
        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        closing_html = renumbered[3]['html']
        self.assertIn('data-slide-counter="1"', closing_html)
        self.assertIn('04 — 04', closing_html)
        self.assertIn('z-index:20', closing_html)

        # Designer-preserved closing slides take the preserved path — same rule.
        preserved = [dict(slide, _designer_keep_html=True) for slide in slides]
        renumbered = engine.renumber_presentation_slides(
            preserved, branding=branding, project_data=project)
        closing_html = renumbered[3]['html']
        self.assertIn('data-slide-counter', closing_html)
        self.assertIn('04 — 04', closing_html)

    def test_renumber_promotes_corner_numbers_on_closing_slide(self):
        """A stale closing number is not always a bottom-corner «NN — NN» leaf —
        it may sit at the top edge as a bare digit or wrap its digits in one
        inline tag. Renumbering must promote those shapes instead of injecting a
        second counter beside them."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        project = {'project_name': 'المشروع'}

        def deck(closing_html):
            return [
                {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
                {'title': 'محتوى', 'type': 'content', 'section_key': 'overview',
                 'html': '<div class="slide">محتوى</div>'},
                {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing',
                 'html': closing_html},
            ]

        # Bare digit pinned to the top edge — promoted in place, marked, updated.
        slides = deck(
            '<div class="slide" dir="rtl" style="position:relative;background:#111;color:#fff;">'
            '<h2>الخاتمة</h2><div>تواصل: 0500000000</div>'
            '<div style="position:absolute;top:40px;right:48px;color:#fff;">73</div></div>')
        closing_html = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)[2]['html']
        self.assertIn('data-slide-counter="1"', closing_html)
        self.assertIn('03 — 03', closing_html)
        self.assertNotRegex(closing_html, r'>\s*73\s*<')
        self.assertIn('top:40px;right:48px', closing_html)
        self.assertIn('0500000000', closing_html)

        # Digits inside one inline wrapper keep the wrapper's styling.
        slides = deck(
            '<div class="slide" dir="rtl" style="position:relative;background:#111;color:#fff;">'
            '<h2>الخاتمة</h2>'
            '<div style="position:absolute;top:40px;right:48px;">'
            '<span style="font-size:20px;color:#C4A35A;">73</span></div></div>')
        closing_html = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)[2]['html']
        self.assertIn('data-slide-counter="1"', closing_html)
        self.assertIn('font-size:20px;color:#C4A35A', closing_html)
        self.assertIn('03 — 03', closing_html)
        self.assertNotRegex(closing_html, r'>\s*73\s*<')

        # An unanchored «NN — NN» leaf is still unmistakably a counter.
        slides = deck(
            '<div class="slide" dir="rtl" style="position:relative;background:#111;color:#fff;">'
            '<h2>الخاتمة</h2><span>12 — 30</span></div>')
        closing_html = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)[2]['html']
        self.assertIn('data-slide-counter="1"', closing_html)
        self.assertIn('03 — 03', closing_html)
        self.assertNotIn('12 — 30', closing_html)

        # A bare digit with no corner anchor is content, not a counter — the
        # injected counter is added without touching it.
        slides = deck(
            '<div class="slide" dir="rtl" style="position:relative;background:#111;color:#fff;">'
            '<h2>الخاتمة</h2><span>عدد الفروع: 73</span></div>')
        closing_html = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)[2]['html']
        self.assertIn('عدد الفروع: 73', closing_html)
        self.assertIn('03 — 03', closing_html)

        # Renumbering is idempotent — promoted counters keep updating, not
        # duplicating.
        slides = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        slides = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        closing_html = slides[2]['html']
        self.assertEqual(closing_html.count('data-slide-counter'), 1)
        self.assertIn('عدد الفروع: 73', closing_html)

    def test_renumber_strips_stray_counter_chrome_from_cover_and_moodboard(self):
        """Cover and moodboard still never receive a managed footer — stray
        counters there are removed, not rewritten."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'accent_color': '#C4A35A',
            'background_color': '#ffffff', 'text_color': '#111111',
            'company_name': 'شركة الاختبار',
        }
        stray = (
            '<div data-slide-counter="1" dir="ltr" '
            'style="position:absolute;bottom:34px;left:48px;">11 — 12</div>'
            '<div style="position:absolute;bottom:20px;right:48px;">12 — 12</div>')
        slides = [
            {'title': 'الغلاف', 'type': 'cover',
             'html': '<div class="slide">غلاف' + stray + '</div>'},
            {'title': 'محتوى', 'type': 'content', 'section_key': 'overview',
             'html': '<div class="slide">محتوى</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing',
             'html': '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
                     'position:relative;background:#111;color:#fff;"><h2>الخاتمة</h2></div>'},
        ]
        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data={'project_name': 'المشروع'})
        self.assertNotIn('data-slide-counter', renumbered[0]['html'])
        self.assertNotRegex(renumbered[0]['html'], r'>\s*\d{1,3}\s*[—–/-]\s*\d{1,3}\s*<')
        # Content slides are untouched by the strip: their counter updates.
        self.assertIn('02 — 03', renumbered[1]['html'])
        # Closing gained its counter.
        self.assertIn('03 — 03', renumbered[2]['html'])

    def test_postprocess_ensures_live_counter_on_closing(self):
        """A generated closing slide keeps a live counter from the start, and a
        model-painted number is promoted so later renumbering can update it."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'accent_color': '#C4A35A',
            'background_color': '#ffffff', 'text_color': '#111111',
            'company_name': 'شركة الاختبار',
        }
        html = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'position:relative;background:#1a1a1a;color:#fff;"><h2>الخاتمة</h2>'
            '<div style="position:absolute;bottom:34px;left:48px;">09 — 09</div></div>')
        finished = engine.postprocess_slide(
            html, 'closing', slide_num=4, slide_title='الخاتمة', total_slides=7,
            branding=branding, project_data={'project_name': 'المشروع'})
        self.assertIn('data-slide-counter', finished)
        self.assertIn('04 — 07', finished)
        self.assertNotIn('09 — 09', finished)
        self.assertIn('الخاتمة', finished)

    def test_frontend_renumber_updates_closing_counter(self):
        """The browser-side renumber treats closing like a numbered slide:
        the chrome-free branch strips only cover and moodboard, while closing
        gets its counter updated, promoted or injected."""
        source = read_frontend_text()
        block = source.split('function renumberTenantSlideHtml', 1)[1]
        free_branch = block.split("['cover', 'moodboard']", 1)[1].split('} else {', 1)[0]
        self.assertIn('data-slide-counter', free_branch)
        self.assertNotIn("closing", free_branch)
        numbered_branch = block.split('} else {', 1)[1]
        self.assertIn("type === 'closing'", numbered_branch)
        self.assertIn('slideCounter', numbered_branch)
