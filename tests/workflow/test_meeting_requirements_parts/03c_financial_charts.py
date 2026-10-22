class MeetingRequirementsTestsPart02bFinancialCharts(MeetingRequirementsTests):

    def test_waterfall_reads_the_named_output_column_not_a_rate_or_duration(self):
        engine = self.application_module.slide_engine
        headers = ['اسم التكلفة', 'التصنيف', 'طريقة الحساب', 'الكمية / المساحة',
                   'السعر / النسبة', 'المدة', 'الناتج']
        rows = [
            ['التصميم والدراسات', 'تصميم ودراسات', 'قيمة ثابتة', '10,000,000', '0', '1', '10,000,000'],
            ['تنفيذ الفندق', 'تنفيذ', 'مساحة × تكلفة متر', '23,400', '10,000', '1', '234,000,000'],
            # A zero-output row used to contribute its 15.25 rate as a cost.
            ['تكلفة التمويل', 'تمويل', 'نسبة من التكلفة', '', '15.25', '', '0'],
        ]
        data = engine._extract_waterfall_chart_data(
            {'headers': headers, 'rows': rows}, model={'inputs': {}}, project_data={})
        self.assertEqual(
            [(item['name'], item['value_sar']) for item in data['items']],
            [('التصميم والدراسات', 10000000.0), ('تنفيذ الفندق', 234000000.0)])
        self.assertEqual(data['total']['value_sar'], 244000000.0)
        self.assertNotIn('تكلفة التمويل', [item['name'] for item in data['items']])

    def test_waterfall_percentages_are_rounded_and_total_follows_the_study(self):
        engine = self.application_module.slide_engine
        headers = ['اسم التكلفة', 'الناتج']
        rows = [
            ['أعمال إنشائية', '50,000,000'],
            ['تصاميم ودراسات', '30,000,000'],
            ['خدمات وتراخيص', '20,000,000'],
        ]
        model = {
            'inputs': {'landCostIncluded': '20,000,000', 'developerCostValue': '15,000,000'},
            'projection': {'adjustedProjectCost': 135000000},
        }
        data = engine._extract_waterfall_chart_data(
            {'headers': headers, 'rows': rows}, model=model, project_data={})
        names = [item['name'] for item in data['items']]
        self.assertIn('قيمة الأرض', names)
        self.assertIn('تكلفة المطور', names)
        self.assertEqual(sum(item['value_sar'] for item in data['items']),
                         data['total']['value_sar'])
        self.assertEqual(data['total']['value_sar'], 135000000.0)
        for item in data['items']:
            self.assertTrue(item['pct_display'].endswith('%'))
            self.assertLessEqual(len(item['pct_display'].rstrip('%').partition('.')[2]), 2)
        self.assertTrue(data['total']['display'].endswith('مليون ر.س'))
        self.assertEqual(data['items'][0]['chart_label'], '50')
        svg = data['summary']['svg_code']
        self.assertIn('37.04%', svg)
        self.assertNotIn('37.037037', svg)

    def test_waterfall_names_an_unitemized_gap_instead_of_hiding_it(self):
        engine = self.application_module.slide_engine
        headers = ['اسم التكلفة', 'الناتج']
        rows = [['أعمال إنشائية', '100,000,000']]
        model = {'inputs': {}, 'projection': {'adjustedProjectCost': 120000000}}
        data = engine._extract_waterfall_chart_data(
            {'headers': headers, 'rows': rows}, model=model, project_data={})
        by_name = {item['name']: item['value_sar'] for item in data['items']}
        self.assertEqual(by_name.get('بنود أخرى'), 20000000.0)
        self.assertEqual(data['total']['value_sar'], 120000000.0)

    def test_financial_clarifications_are_an_editorial_page_not_a_table(self):
        engine = self.application_module.slide_engine
        clarifications = '\n'.join([
            '1- البيع والتأجير: يتم بيع وحدات المشروع على الخارطة وفق نظام البيع على الخارطة، '
            'وتأجير الوحدات التجارية بعقود طويلة الأجل مع مراعاة أنظمة وزارة التجارة والاستثمار.',
            '2- التكاليف: تشمل جميع تكاليف التطوير المباشرة وغير المباشرة، بما في ذلك أعمال '
            'البنية التحتية والتشطيبات والتجهيزات، واحتُسبت على أساس الأسعار السائدة في السوق.',
            '3- التمويل: احتُسب التمويل على أساس 60% من إجمالي التكلفة، على أن يتم السحب على '
            'دفعات وفق مراحل التطوير، وتبدأ عملية السداد بعد اكتمال مرحلة الإنشاء الرئيسية.',
            '4- الإيرادات: احتُسبت على أساس متوسط أسعار البيع والتأجير في المنطقة، مع نسبة '
            'إشغال متحفظة في السنة الأولى وزيادة تدريجية حتى الوصول إلى النسبة المستهدفة.',
            '5- المصروفات: تشمل الصيانة والتأمين والرسوم البلدية وأتعاب إدارة الأصول، وقُدرت '
            'كنسبة من الإيرادات التشغيلية بناءً على بيانات مشاريع مماثلة في المنطقة.',
            '6- المخاطر: تشمل مخاطر الأسعار ومخاطر التأخير ومخاطر الإشغال، وقد أُدرجت ضمن '
            'تحليل الحساسية المعتمد في الدراسة المالية.',
        ])
        model = {
            'inputs': {'projectCost': 1000, 'financialClarifications': clarifications},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '15. الإيضاحات'},
                {'type': 'fields', 'rows': [['الإيضاحات', clarifications]]},
            ]},
        }
        project = {'project_name': 'مشروع تجريبي', 'financial_study_model': model}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        clarification_slides = [
            slide for slide in plan['slides']
            if slide.get('section_key') == 'financial'
            and slide.get('design_style') == 'clarifications'
        ]
        self.assertEqual(len(clarification_slides), 1, clarification_slides)
        slide = clarification_slides[0]
        self.assertIn('الإيضاحات', slide.get('title', ''))
        html = engine._build_structured_fallback_slide(
            slide, project, {'primary_color': '#005f78', 'accent_color': '#c59a58'})
        self.assertIn('data-financial-clarifications="1"', html)
        self.assertIn('data-financial-clarifications-columns="2"', html)
        self.assertNotIn('<table', html.lower())
        self.assertIn('البيع والتأجير', html)
        self.assertEqual(html.count('<p style="margin:0 0 10px'), 6)

    def test_combo_chart_mirrors_the_cashflow_table_and_invents_no_series(self):
        engine = self.application_module.slide_engine
        part = {
            'headers': ['السنة', 'صافي تدفق المشروع', 'الرصيد التراكمي'],
            'rows': [
                ['1', '(10,000,000)', '(10,000,000)'],
                ['2', '25,000,000', '15,000,000'],
                ['3', '0', '15,000,000'],
            ],
        }
        data = engine._extract_combo_chart_data(part, model={'tables': {}}, project_data={})
        self.assertEqual(
            [(item['net_val'], item['cum_val']) for item in data['items']],
            [(-10000000.0, -10000000.0), (25000000.0, 15000000.0), (0.0, 15000000.0)])
        empty = engine._extract_combo_chart_data(None, {'tables': {}, 'report': {}}, {})
        self.assertEqual(empty['items'], [])
        self.assertFalse(empty['summary'].get('svg_code'))
