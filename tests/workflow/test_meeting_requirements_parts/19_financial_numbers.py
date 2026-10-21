class MeetingRequirementsTestsPart19(MeetingRequirementsTests):
    """Issue 02 — the numbers a slide shows must be the numbers the client approved.

    The financial study keeps raw decimals (a ROI of 0.2345) and raw floats
    (189750000.00000004). A deck that copies them contradicts the screen, so
    every number leaves the engine through one formatter.
    """

    def test_presentation_numbers_keep_their_grouping_and_drop_float_artifacts(self):
        engine = self.application_module.slide_engine

        # A number that already carries thousands separators never matched the
        # formatter, so it reached the deck exactly as the client wrote it —
        # in the wrong grouping, or with no grouping at all.
        self.assertIn('923,938,343', engine._format_presentation_numeric_text(
            '<div>تكلفة المشروع 923,938,343 ريال</div>'))
        # A number written in the European grouping keeps every digit and
        # comes out in the grouping this system uses.
        self.assertIn('923,938.343', engine._format_presentation_numeric_text(
            '<div>تكلفة المشروع 923.938,343 ريال</div>'))
        # A plain decimal is never read as a thousands separator.
        self.assertIn('12.345', engine._format_presentation_numeric_text(
            '<div>المساحة 12.345 م²</div>'))

        # A plain large number gets the same grouping.
        self.assertIn('923,938,343', engine._format_presentation_numeric_text(
            '<div>تكلفة المشروع 923938343 ريال</div>'))

        # A float artifact is rounded half-up to the hundredth.
        self.assertIn('189,750,000', engine._format_presentation_numeric_text(
            '<div>إجمالي التكلفة 189750000.00000004 ريال</div>'))

        # A coordinate and a year keep every digit they were given.
        self.assertIn('24.713605', engine._format_presentation_numeric_text(
            '<div>خط العرض 24.713605</div>'))
        self.assertIn('2024', engine._format_presentation_numeric_text(
            '<div>سنة 2024</div>'))

    def test_financial_indicators_leave_the_engine_as_display_strings(self):
        engine = self.application_module.slide_engine
        model = {
            'projection': {
                'roi': 0.2345,
                'projectIrr': 0.1812,
                'projectCost': 189750000,
                'payback': 5.5,
                'totalBuiltUpArea': 70000,
            },
        }
        rows = dict((label, value) for label, value in
                    engine._financial_indicator_display_rows(model, {}))

        # A ratio leaves as the percentage the screen shows.
        self.assertEqual(rows.get('ROI'), '23.45%')
        self.assertEqual(rows.get('Project IRR'), '18.12%')
        # A money figure leaves grouped.
        self.assertEqual(rows.get('إجمالي تكلفة المشروع'), '189,750,000')
        # A year keeps its decimals without a thousands separator.
        self.assertEqual(rows.get('فترة استرداد رأس المال'), '5.5')

    def test_the_client_display_values_win_over_the_stored_projection(self):
        engine = self.application_module.slide_engine
        model = {
            'projection': {'roi': 0.2345, 'projectCost': 189750000},
            'formattedIndicators': {'roi': '23.45%', 'projectCost': '189,750,000'},
        }
        rows = dict((label, value) for label, value in
                    engine._financial_indicator_display_rows(model, {}))
        self.assertEqual(rows.get('ROI'), '23.45%')
        self.assertEqual(rows.get('إجمالي تكلفة المشروع'), '189,750,000')

    def test_the_financial_summary_table_never_shows_a_raw_ratio(self):
        engine = self.application_module.slide_engine
        model = {
            'projection': {'roi': 0.2345, 'projectCost': 189750000},
        }
        headers, rows = engine._fallback_table_data(
            {'content_source': 'financial_indicators'}, {'financial_study_model': model})
        values = [str(cell) for row in rows for cell in row]
        self.assertIn('23.45%', values)
        self.assertNotIn('0.2345', values)
        self.assertIn('189,750,000', values)

    def test_chart_amounts_in_millions_are_rounded_to_the_hundredth(self):
        engine = self.application_module.slide_engine
        self.assertEqual(engine._format_sar_display(14354123.456789), '14.35 ر.س')
        self.assertEqual(engine._format_sar_display(92000), '92,000 ر.س')

    def test_the_client_sends_the_approved_display_values_with_the_model(self):
        source = read_frontend_text()
        self.assertIn('formattedIndicators: collectFinancialFormattedIndicators()', source)
        self.assertIn('function collectFinancialFormattedIndicators()', source)
        # The percentage is prepared on screen, where the ratio is multiplied
        # by a hundred, so the deck never has to guess the unit.
        self.assertIn('resultPercent(value * 100)', source)
