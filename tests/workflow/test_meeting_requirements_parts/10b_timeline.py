class MeetingRequirementsTestsPart10(MeetingRequirementsTests):
    def test_timeline_slide_renders_a_colored_gantt_deterministically(self):
        """The timeline section carries a fixed Gantt: every dated phase is a
        colored bar on a shared month axis — the same reading as the project-data
        board — and the model can no longer drop the chart or improvise a
        dots-on-a-line design."""
        engine = self.application_module.slide_engine
        module = self.application_module
        rows = [
            {'name': 'التراخيص', 'start': '2030-02-01', 'end': '2030-06-30',
             'notes': 'بانتظار الأمانة'},
            {'name': 'الهيكل الإنشائي', 'start': '2030-05-01', 'end': '2031-02-28',
             'notes': ''},
            {'name': 'مرحلة بلا تاريخ'},
        ]
        source = {
            'project_name': 'مشروع الاختبار',
            'timeline_start_date': '2030-02-01',
            'timeline_end_date': '2031-12-31',
            'timeline_table_data': json.dumps(rows, ensure_ascii=False),
        }
        slide = {
            'title': 'الجدول الزمني ومراحل التطوير', 'type': 'content',
            'section_key': 'timeline', 'design_style': 'timeline',
            'content_source': 'timeline_table_data',
        }
        branding = {'primary_color': '#0b1f33', 'accent_color': '#c59a58',
                    'secondary_color': '#0ea5e9'}

        html = engine._build_timeline_slide(slide, source, branding, slide_num=5, total_slides=20)
        self.assertIn('data-timeline-gantt="1"', html)
        self.assertIn('التراخيص', html)
        self.assertIn('الهيكل الإنشائي', html)
        self.assertIn('بانتظار الأمانة', html)
        # A shared month axis labels the bars — anchored at the project start.
        self.assertIn('2/2030', html)
        self.assertIn('right:0.00%', html)
        # Colored bars rotate through the brand palette.
        self.assertIn('background:#0b1f33', html)
        self.assertIn('background:#c59a58', html)
        # Undated phases wait in the unscheduled lane instead of being dropped.
        self.assertIn('مراحل غير مجدولة', html)
        self.assertIn('مرحلة بلا تاريخ', html)
        self.assertIn('data-timeline-bar="1"', html)

        # The slide is a fixed layout: generation never asks the model for it.
        calls = []
        html2 = engine.generate_single_slide(
            'sys', slide, 5, 20, branding,
            lambda *a, **k: calls.append(1) or {}, project_data=source)
        self.assertEqual(calls, [])
        self.assertIn('data-timeline-gantt', html2)

        # The designer chat owns the same canonical rebuild when asked for the chart.
        self.assertTrue(module._is_project_timeline_slide(
            title='الجدول الزمني ومراحل التطوير'))
        self.assertTrue(module._is_project_timeline_slide(
            content_source='timeline_table_data'))
        self.assertTrue(module._is_project_timeline_slide(html=html))
        self.assertTrue(module._designer_requests_timeline_chart('حط مخطط زمني للمراحل'))
        self.assertTrue(module._designer_requests_timeline_chart('add a gantt chart'))
        self.assertFalse(module._designer_requests_timeline_chart('غير لون الخلفية'))
