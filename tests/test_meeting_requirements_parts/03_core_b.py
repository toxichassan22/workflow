class MeetingRequirementsTestsPart02(MeetingRequirementsTests):

    def test_location_map_slides_are_rehomed_from_visual_sections(self):
        engine = self.application_module.slide_engine
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مرجع الموقع العام', 'type': 'map_overview', 'section_key': 'interior'},
            {'title': 'خريطة الطرق', 'type': 'content', 'section_key': 'exterior',
             'content_source': 'main_roads'},
            {'title': 'الخريطة', 'type': 'content', 'section_key': 'plans',
             'content_source': 'location_polygon'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, {'project_name': 'المشروع', 'location_address': 'جدة'}, {})
        map_slides = [slide for slide in plan['slides']
                      if slide.get('type', '').startswith('map_')]
        self.assertEqual({slide.get('section_key') for slide in map_slides}, {'location'})
        self.assertTrue(any(slide.get('content_source') == 'main_roads' for slide in map_slides))
        self.assertTrue(any(slide.get('content_source') == 'location_polygon' for slide in map_slides))
        self.assertTrue(all(slide.get('section_key') != 'interior' for slide in plan['slides']
                            if slide.get('type') == 'map_overview'))

    def test_directional_diagram_is_canonicalized_once(self):
        engine = self.application_module.slide_engine
        project = {'project_name': 'المشروع', 'boundary_lengths': 'شمال 20م',
                   'surrounding_streets': 'شارع شمالي'}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'حدود الأرض والواجهات', 'type': 'content', 'section_key': 'land',
             'design_style': 'diagram', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'مخطط اتجاهي لحدود الأرض', 'type': 'content', 'section_key': 'land',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        diagrams = [slide for slide in plan['slides']
                    if slide.get('content_source') == 'land_boundary_diagram']
        self.assertEqual(len(diagrams), 1, diagrams)
        self.assertEqual(sum(slide.get('design_style') == 'diagram' for slide in plan['slides']), 1)

    def test_hidden_land_analysis_data_keeps_boundary_diagram_in_full_plan(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'المشروع',
            'land_documents_analysis_data': json.dumps({
                'parcels': [{
                    'directions': {
                        'north': {'boundary_length_m': 109, 'street_name': 'شارع شمالي', 'street_width_m': 20},
                        'south': {'boundary_length_m': 98, 'uses': 'جار'},
                    }
                }]
            }, ensure_ascii=False),
        }
        plan = engine.normalize_presentation_plan(
            {'slides': [{'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
                        {'title': 'الخاتمة', 'type': 'closing'}]}, project, {})
        diagram = next(slide for slide in plan['slides']
                       if slide.get('content_source') == 'land_boundary_diagram')
        self.assertEqual(diagram.get('section_key'), 'land')
        self.assertEqual(diagram.get('design_style'), 'diagram')

    def test_location_only_generation_does_not_include_land_boundary_diagram(self):
        engine = self.application_module.slide_engine
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover', 'section_key': 'cover'},
            {'title': 'الفهرس', 'type': 'index', 'section_key': 'index'},
            {'title': 'تحليل الأرض', 'type': 'section_divider', 'section_key': 'land'},
            {'title': 'مخطط اتجاهي لحدود الأرض', 'type': 'content', 'section_key': 'land',
             'content_source': 'land_boundary_diagram', 'design_style': 'diagram'},
            {'title': 'تحليل الموقع الجغرافي', 'type': 'section_divider', 'section_key': 'location'},
            {'title': 'موقع المشروع', 'type': 'content', 'section_key': 'location'},
            {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing'},
        ]}
        filtered = engine.filter_presentation_plan_sections(plan, ['location'])
        self.assertIsNotNone(filtered)
        diagrams = [slide for slide in filtered['slides']
                    if slide.get('content_source') == 'land_boundary_diagram']
        self.assertEqual(len(diagrams), 0)
        filtered_land = engine.filter_presentation_plan_sections(plan, ['land'])
        land_diagrams = [slide for slide in filtered_land['slides']
                         if slide.get('content_source') == 'land_boundary_diagram']
        self.assertEqual(len(land_diagrams), 1)
        self.assertEqual(land_diagrams[0].get('section_key'), 'land')

    def test_land_boundary_diagram_includes_direction_setbacks_and_streets(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الواجهة',
            'setbacks': 'أمامي 4م، خلفي 2م، جانبي 2م',
            'surrounding_streets': 'شارع العليا شمالاً، جار جنوباً، شارع فرعي شرقاً، طريق رئيسي غرباً',
            'land_documents_analysis_data': json.dumps({
                'parcels': [{
                    'directions': {
                        'north': {'boundary_length_m': 100, 'street_name': 'شارع العليا', 'setback': '4م'},
                        'south': {'boundary_length_m': 80, 'uses': 'جار', 'setback': '2م'},
                        'east': {'boundary_length_m': 60, 'street_name': 'شارع فرعي', 'setback': '2.5م'},
                        'west': {'boundary_length_m': 50, 'uses': 'طريق رئيسي', 'setback': '3م'},
                    }
                }]
            }, ensure_ascii=False),
        }
        html = engine.generate_single_slide(
            'system', {'title': 'مخطط اتجاهي لحدود الأرض', 'type': 'content',
                       'section_key': 'land', 'design_style': 'diagram',
                       'content_source': 'land_boundary_diagram'},
            4, 12, {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('boundary diagram must be deterministic'),
            project_data=project)
        self.assertIn('data-boundary-diagram="1"', html)
        self.assertIn('الارتداد:', html)
        self.assertIn('4م', html)
        self.assertIn('شارع العليا', html)

    def test_map_access_omits_empty_columns_when_roads_have_names_only(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع النخيل',
            'main_roads': [
                {'name': 'طريق الملك فهد'},
                {'name': 'طريق الدائري الشمالي'},
                {'name': 'طريق العليا العام'},
            ],
        }
        html = engine.generate_single_slide(
            'system', {'title': 'خريطة الطرق ومحاور الوصول', 'type': 'map_access',
                       'section_key': 'location', 'content_source': 'main_roads'},
            5, 12, {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('map_access fallback must be deterministic'),
            project_data=project)
        self.assertIn('طريق الملك فهد', html)
        self.assertIn('الطريق / المحور', html)
        self.assertNotIn('العرض (م)', html)
        self.assertNotIn('المسافة', html)

    def test_map_catchment_extracts_duration_minutes_and_category(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع النخيل',
            'catchment_areas': [
                {'name': 'مستشفى الملك فيصل التخصصي', 'category': 'صحي', 'duration_minutes': 8, 'distance_km': 4.5},
                {'name': 'جامعة الملك سعود', 'category': 'تعليمي', 'duration_minutes': 12, 'distance_km': 9.0},
                {'name': 'الرياض بارك', 'category': 'تجاري / ترفيهي', 'duration_minutes': 15, 'distance_km': 14.2},
            ],
        }
        html = engine.generate_single_slide(
            'system', {'title': 'خريطة المنطقة ونطاق التأثير', 'type': 'map_catchment',
                       'section_key': 'location', 'content_source': 'catchment_areas'},
            6, 12, {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('map_catchment fallback must be deterministic'),
            project_data=project)
        self.assertIn('مستشفى الملك فيصل التخصصي', html)
        self.assertIn('صحي', html)
        self.assertIn('8', html)
        self.assertIn('12', html)
        self.assertNotIn('>—<', html)

    def test_site_analysis_chunks_into_two_slides_and_uses_side_by_side_layout(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع النخيل',
            'site_analysis': (
                'يتميز موقع المشروع بموقع استراتيجي في قلب المدينة بالقرب من أهم المحاور.\n\n'
                'يتصل الموقع مباشرة بطرق شريانية سريعة تسهل حركة الدخول والخروج وانسيابية المرور.\n\n'
                'تحيط بالمشروع كثافة سكانية عالية وقوة شرائية متميزة تدعم نجاح المشروع التجاري.\n\n'
                'تتوافر في محيط الموقع كافة خدمات البنية التحتية والمرافق الحكومية والترفيهية.\n\n'
                'يمثل الموقع فرصة استثمارية واعدة للتطوير العقاري المتعدد الاستخدامات.'
            ),
        }
        plan = engine.normalize_presentation_plan(
            {'slides': [
                {'title': 'الغلاف', 'type': 'cover', 'section_key': 'cover'},
                {'title': 'ملخص الموقع الجغرافي', 'type': 'content', 'section_key': 'location', 'content_source': 'site_analysis'},
                {'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing'},
            ]},
            project,
            {},
        )
        site_slides = [s for s in plan['slides'] if str(s.get('content_source', '')).startswith('site_analysis')]
        self.assertEqual(len(site_slides), 2)
        self.assertIn('(1/2)', site_slides[0]['title'])
        self.assertIn('(2/2)', site_slides[1]['title'])
        self.assertTrue(site_slides[0].get('requires_image'))
        self.assertIn('##MAP_OVERVIEW##', site_slides[0].get('image_tokens', []))
        self.assertFalse(site_slides[1].get('requires_image'))
        self.assertEqual(site_slides[1].get('image_tokens', []), [])

        html1 = engine.generate_single_slide(
            'system', site_slides[0], 2, 4,
            {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('site_analysis must be deterministic fallback'),
            project_data=project)
        self.assertIn('##MAP_OVERVIEW##', html1)
        self.assertNotIn('data-map-summary-card', html1)

        html2 = engine.generate_single_slide(
            'system', site_slides[1], 3, 4,
            {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('site_analysis must be deterministic fallback'),
            project_data=project)
        self.assertNotIn('##MAP_OVERVIEW##', html2)
        self.assertNotIn('data-map-summary-card', html2)

    def test_boundary_diagram_is_deterministic_and_does_not_call_model(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الواجهة',
            'land_documents_analysis_data': json.dumps({
                'parcels': [{'directions': {
                    'north': {'boundary_length_m': 109, 'street_name': 'شارع شمالي', 'street_width_m': 20},
                    'south': {'boundary_length_m': 98, 'uses': 'جار'},
                    'east': {'boundary_length_m': 80, 'street_name': 'شارع شرقي'},
                    'west': {'boundary_length_m': 59.5, 'uses': 'طريق الكورنيش'},
                }}]
            }, ensure_ascii=False),
        }
        html = engine.generate_single_slide(
            'system', {'title': 'مخطط اتجاهي لحدود الأرض', 'type': 'content',
                       'section_key': 'location', 'design_style': 'diagram',
                       'content_source': 'land_boundary_diagram'},
            4, 12, {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('boundary diagram must be deterministic'),
            project_data=project)
        self.assertIn('data-boundary-diagram="1"', html)
        self.assertEqual(len(re.findall(r'data-boundary-direction=', html)), 4)
        for value in ('109', '98', '80', '59.5', 'شارع شمالي', 'طريق الكورنيش'):
            self.assertIn(value, html)

    def test_legacy_boundary_title_is_repaired_before_model_generation(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع الواجهة',
            'boundary_lengths': 'شمال 20م، جنوب 18م',
            'surrounding_streets': 'شارع شمالي، جار جنوباً',
        }
        html = engine.generate_single_slide(
            'system', {'title': 'مخطط اتجاهي لحدود الأرض', 'type': 'content',
                       'section_key': 'land', 'design_style': 'diagram'},
            9, 72, {'primary_color': '#005f78', 'accent_color': '#c59a58'},
            lambda *_args, **_kwargs: self.fail('legacy boundary title must be deterministic'),
            project_data=project)
        self.assertIn('data-boundary-diagram="1"', html)
        self.assertEqual(len(re.findall(r'data-boundary-direction=', html)), 4)

    def test_content_logos_tables_and_fitted_html_keep_readable_sizes(self):
        engine = self.application_module.slide_engine
        html = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px;background:#fff;color:#111">'
            '<img src="##LOGO##" style="height:22px"><table><tr><th style="font-size:8px">البند</th>'
            '<td style="font-size:7px">القيمة</td></tr></table></div>',
            'content', {}, {'primary_color': '#123456', '_logo_tone': 'dark'},
            slide_num=3, slide_title='الدراسة المالية', total_slides=5)
        logo = next(tag for tag in re.findall(r'<img\b[^>]*>', html) if '/assets/logo.png' in tag)
        self.assertIn('height:48px!important', logo)
        self.assertIn('font-size:13px!important', html)
        self.assertIn('font-size:12px!important', html)
        index_source = read_frontend_text()
        self.assertIn('const VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 30;', index_source)
        self.assertIn('await repairVisualConceptStoredImages();', index_source)
        self.assertIn('slideObj.html = stage.innerHTML;', index_source)

    def test_chart_limit_summary_order_and_sparse_content_rules(self):
        engine = self.application_module.slide_engine
        parts = [
            {'type': 'heading', 'level': 3, 'text': 'التكاليف والاستثمار'},
            {'type': 'fields', 'rows': [[f'تكلفة {index}', str(index * 100)] for index in range(1, 8)]},
            {'type': 'heading', 'level': 3, 'text': 'مؤشرات العائد والاسترداد'},
            {'type': 'fields', 'rows': [['ROI', '18%'], ['Project IRR', '15%'], ['فترة الاسترداد', '6 سنوات']]},
        ]
        parts.extend([
            {'type': 'heading', 'level': 2, 'text': 'طبيعة وحدات المشروع'},
            {'type': 'fields', 'rows': [['هل الوحدات بيعية أم تأجيرية؟', 'مختلطة']]},
        ])
        for index, title in enumerate(('الإيرادات السنوية', 'تكاليف التشغيل', 'التدفقات النقدية',
                                       'تحليل الحساسية', 'مقارنة التمويل'), 1):
            parts.extend([
                {'type': 'heading', 'level': 2, 'text': title},
                {'type': 'table', 'headers': ['البند', 'القيمة'],
                 'rows': [[f'{title} {row}', str(index * row * 10)] for row in range(1, 4)]},
            ])
        project = {'project_name': 'المشروع', 'financial_study_model': {
            'inputs': {'projectCost': 1000}, 'report': {'parts': parts},
        }}
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'رسم السوق', 'type': 'content', 'section_key': 'market',
             'design_style': 'chart', 'chart_type': 'bar', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, project, {})
        self.assertFalse(any(slide.get('chart_type') for slide in plan['slides']
                             if slide.get('section_key') != 'financial'))
        financial = [slide for slide in plan['slides']
                     if slide.get('section_key') == 'financial' and slide.get('type') == 'content']
        self.assertLessEqual(sum(bool(slide.get('chart_type')) for slide in financial), 3)
        summaries = [slide for slide in financial
                     if str(slide.get('content_source') or '').startswith('financial_summary:')]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(financial[-len(summaries):], summaries)
        self.assertFalse(any(slide.get('row_count') == 1 for slide in financial[:-len(summaries)]))

    def test_landmarks_and_map_summaries_require_maps_and_marker_aware_layout(self):
        engine = self.application_module.slide_engine
        app_module = self.application_module
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        located = app_module._ensure_required_location_slides(plan, {
            'location_lat': 21.6, 'location_lng': 39.1,
            'nearby_landmarks': 'معلم — 2 كم — 5 دقائق',
        })
        landmarks = next(slide for slide in located['slides'] if slide.get('type') == 'map_landmarks')
        self.assertEqual(landmarks.get('image_tokens'), ['##MAP_LANDMARKS##'])
        landmark_project = {'landmarks_matrix': [{
            'name': 'واجهة جدة البحرية', 'distance': '2.6 كم', 'duration': '8 دقائق'}]}
        landmark_note = engine._slide_source_data_note(landmarks, landmark_project)
        for value in ('واجهة جدة البحرية', '2.6 كم', '8 دقائق'):
            self.assertIn(value, landmark_note)
            self.assertIn(value, engine._required_slide_texts(landmarks, landmark_project))
        self.assertEqual(app_module._generation_map_marker_side({
            'map_lng': 39.1, 'map_centers': {'overview': {'lng': 39.2}}}, {}), 'left')
        self.assertEqual(app_module._generation_map_marker_side({
            'map_lng': 39.3, 'map_centers': {'overview': {'lng': 39.2}}}, {}), 'right')
        project = {
            'project_name': 'المشروع', 'location_lat': 21.6, 'location_lng': 39.1,
            'site_analysis': 'ملخص الموقع',
            'executive_content': json.dumps({'summary': 'الملخص التنفيذي'}, ensure_ascii=False),
            '_map_marker_side': 'right',
        }
        normalized = engine.normalize_presentation_plan(plan, project, {})
        exec_summary = next(item for item in normalized['slides']
                            if str(item.get('content_source') or '').startswith('executive_content.summary'))
        # The executive summary section is text-only: no maps or images are
        # ever reserved on it, so the layout always uses the full width.
        self.assertEqual(exec_summary.get('image_tokens') or [], [])
        site_slide = next(item for item in normalized['slides'] if item.get('content_source') == 'site_analysis')
        self.assertIn('##MAP_OVERVIEW##', site_slide.get('image_tokens') or [])
        message = engine.build_slide_user_msg(site_slide, 3, len(normalized['slides']), {}, project)
        self.assertIn('علامة الموقع في النصف الأيمن', message)
        self.assertIn('ضع بطاقة الملخص في اليسار', message)
        finished = engine.finalize_slide_html(
            '<div class="slide"><img data-map-summary-background src="##MAP_OVERVIEW##">'
            '<div data-map-summary-card>ملخص الموقع</div></div>',
            'content', project, {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
            content_source='site_analysis')
        self.assertIn('left:24px!important', finished)
        self.assertIn('width:40%!important', finished)
        self.assertIn('object-fit:contain!important', finished)
        app_source = read_module_source('app.py')
        self.assertEqual(app_source.count("project_data['_map_marker_side'] = _generation_map_marker_side(images, project_data)"), 2)

    def test_map_summary_structure_is_repaired_without_rejecting_the_slide(self):
        engine = self.application_module.slide_engine
        responses = iter([
            '<div class="slide" style="background:#fff;color:#111"><img src="##MAP_OVERVIEW##"><p>ملخص الموقع</p></div>',
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'ملخص الموقع', 'type': 'content', 'section_key': 'location',
                       'content_source': 'site_analysis', 'image_tokens': ['##MAP_OVERVIEW##']},
            3, 5, {'primary_color': '#123456'}, generated,
            project_data={'site_analysis': 'ملخص الموقع', '_map_marker_side': 'right'})
        repaired = engine.finalize_slide_html(
            html, 'content', {'_map_marker_side': 'right'}, {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
            content_source='site_analysis')
        self.assertIn('data-map-summary-card', repaired)
        self.assertIn('data-map-summary-background', repaired)
        self.assertEqual(len(prompts), 1)

    def test_swot_section_keeps_one_canonical_slide_and_adds_risk_register(self):
        engine = self.application_module.slide_engine
        project = {
            'market_study_data': json.dumps({'swot': {
                'strengths': 'موقع قوي', 'weaknesses': 'تكلفة مرتفعة',
                'opportunities': 'نمو الطلب', 'threats': 'المنافسة',
            }}, ensure_ascii=False),
            'executive_content': json.dumps({'risks': 'مخاطر مكررة وطرق معالجتها'}, ensure_ascii=False),
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'تحليل SWOT للسوق والمخاطر', 'type': 'content', 'section_key': 'swot_risks',
             'content_source': 'market_study_data.swot', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'مصفوفة SWOT وسجل المخاطر', 'type': 'content', 'section_key': 'swot_risks',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'تحليل المخاطر وطرق المعالجة', 'type': 'content', 'section_key': 'swot_risks',
             'content_source': 'executive_content.risks', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, project, {})
        slides = [slide for slide in plan['slides']
                  if slide.get('section_key') == 'swot_risks' and slide.get('type') == 'content']
        self.assertEqual(len(slides), 2, slides)
        self.assertEqual(
            [slide.get('content_source') for slide in slides],
            ['market_study_data.swot', 'executive_content.risks'],
        )
        note = engine._slide_source_data_note(slides[0], project)
        for value in ('موقع قوي', 'تكلفة مرتفعة', 'نمو الطلب', 'المنافسة'):
            self.assertIn(value, note)
        risk_slide = slides[1]
        risk_html = engine.generate_single_slide(
            'system', risk_slide, 4, 10, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('risk analysis must be deterministic'),
            project_data=project,
        )
        self.assertIn('data-risk-register', risk_html)
        self.assertIn('مخاطر مكررة وطرق معالجتها', risk_html)

    def test_closing_uses_main_image_contacts_and_brand_overlay(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'THE VIEW', 'contact_name': 'أحمد', 'contact_position': 'مدير الاستثمار',
            'contact_phone': '0500000000', 'contact_email': 'a@example.test',
            'contact_website': 'example.test', 'contact_address': 'جدة',
            'contact_social_media': '@theview',
        }
        images = {'cover': 'available'}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, images)
        closing = plan['slides'][-1]
        self.assertEqual(closing.get('content_source'), 'contact_closing')
        self.assertEqual(closing.get('image_tokens'), ['##IMAGE_COVER##'])
        note = engine._slide_source_data_note(closing, project)
        for value in ('أحمد', 'مدير الاستثمار', '0500000000', 'a@example.test', 'example.test', 'جدة', '@theview'):
            self.assertIn(value, note)
        empty_note = engine._slide_source_data_note(
            {'content_source': 'contact_closing'}, {'project_name': 'THE VIEW'})
        self.assertIn('THE VIEW', empty_note)
        self.assertIn('شكر', empty_note)
        rules = self.application_module.build_design_rules({
            'primary_color': '#7a0c0c', 'secondary_color': '#254b66',
            'background_color': '#fff', 'text_color': '#111',
        })
        self.assertIn('rgba(122,12,12', rules)
        self.assertNotIn('rgba(11,31,51', rules)
        cover = engine.finalize_slide_html(
            '<div class="slide" style="background:linear-gradient(135deg,rgba(11,31,51,0.85),rgba(11,31,51,0.55))"></div>',
            'cover', project, {'primary_color': '#7a0c0c'})
        self.assertIn('rgba(122,12,12,0.85)', cover)
        self.assertNotIn('rgba(11,31,51', cover)
        enforced_cover = engine.finalize_slide_html(
            '<div class="slide"><div data-cover-overlay style="background:#000"></div></div>',
            'cover', project, {'primary_color': '#7a0c0c'})
        self.assertIn('rgba(122,12,12,0.88)', enforced_cover)
        sanitized_closing = engine.finalize_slide_html(
            '<div class="slide"><p>البريد: fake@example.test</p><p>البريد: a@example.test</p>'
            '<p>الهاتف: 0599999999</p></div>', 'closing', project,
            {'primary_color': '#7a0c0c'})
        self.assertNotIn('fake@example.test', sanitized_closing)
        self.assertNotIn('0599999999', sanitized_closing)
        self.assertIn('a@example.test', sanitized_closing)
        divider = engine.build_section_divider_slide(
            {'title': 'القسم'}, 3, 5, {'primary_color': '#7a0c0c'},
            {'project_logo': '/logo.png'})
        self.assertGreaterEqual(divider.count('height:80px'), 2)

    def test_deterministic_fallback_prevents_media_and_financial_503(self):
        engine = self.application_module.slide_engine

        def incomplete(_system, _user_message, **_kwargs):
            return {'choices': [{'message': {'content': '<div class="slide">ناقص</div>'}}]}

        media = engine.generate_single_slide(
            'system', {'title': 'صور الأرض', 'type': 'content', 'design_style': 'image',
                       'image_tokens': ['##LAND_PHOTO_1##', '##LAND_PHOTO_2##']},
            3, 5, {'primary_color': '#123456'}, incomplete, max_retries=0, project_data={})
        self.assertIn('##LAND_PHOTO_1##', media)
        self.assertIn('##LAND_PHOTO_2##', media)
        project = {'financial_study_model': {'inputs': {'projectCost': 1}, 'report': {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'الإيرادات'},
            {'type': 'table', 'headers': ['السنة', 'الإيراد'], 'rows': [['2027', '1,500,000']]},
        ]}}}
        financial = engine.generate_single_slide(
            'system', {'title': 'الإيرادات', 'type': 'content', 'section_key': 'financial',
                       'content_source': 'financial_report:1:0:1', 'design_style': 'table'},
            4, 5, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('financial report slides must be deterministic'),
            max_retries=0, project_data=project)
        self.assertIn('2027', financial)
        self.assertIn('1,500,000', financial)

    def test_misclassified_financial_slide_is_rehomed_and_never_calls_model(self):
        engine = self.application_module.slide_engine
        project = {'project_name': 'مشروع مالي', 'financial_study_model': {
            'inputs': {'projectCost': 1000},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'الإيرادات'},
                {'type': 'table', 'headers': ['السنة', 'الإيراد'],
                 'rows': [['2027', '1,500,000']]},
            ]},
        }}
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الإيرادات', 'type': 'content', 'section_key': 'timeline',
             'content_source': 'financial_report:1:0:1', 'design_style': 'table'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, project, {})
        # The canonical plan may replace a hand-authored financial report slide
        # with its deterministic financial section. Test the important contract
        # directly as well as confirming that the normalized plan contains that
        # section.
        self.assertTrue(any(slide.get('section_key') == 'financial'
                            for slide in plan['slides']))
        financial_plan = engine._normalize_financial_slide(raw['slides'][2])
        self.assertEqual(financial_plan.get('section_key'), 'financial')
        html = engine.generate_single_slide(
            'system', financial_plan, 4, 8, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('financial slides must bypass SOL'),
            project_data=project,
        )
        self.assertIn('<table', html.lower())
        self.assertIn('1,500,000', html)

    def test_unplanned_chart_retries_as_table(self):
        engine = self.application_module.slide_engine
        responses = iter([
            '<div class="slide" style="background:#fff;color:#111"><div class="chart">رسم</div></div>',
            '<div class="slide" style="background:#fff;color:#111"><table><tr><td>بيانات</td></tr></table></div>',
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'بيانات السوق', 'type': 'content', 'section_key': 'market',
                       'design_style': 'table', 'chart_type': ''},
            3, 5, {'primary_color': '#123456'}, generated, project_data={})
        self.assertIn('<table', html)
        self.assertEqual(len(prompts), 2)

    def test_cover_without_overlay_marker_does_not_stop_generation(self):
        engine = self.application_module.slide_engine
        responses = iter([
            '<div class="slide" style="background:#fff;color:#111"><div>الغلاف</div></div>',
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'الغلاف', 'type': 'cover'}, 1, 5,
            {'primary_color': '#7a0c0c'}, generated, project_data={})
        self.assertIn('class="slide"', html)
        self.assertIn('data-cover-overlay', prompts[0])
        self.assertEqual(len(prompts), 1)

    def test_generic_repeated_badges_and_placeholder_slides_are_removed(self):
        engine = self.application_module.slide_engine
        cleaned = engine.postprocess_slide(
            '<div class="slide"><div class="badge">* مشروع متعدد الاستخدامات *</div><p>المحتوى</p></div>',
            'content', slide_num=3, slide_title='تحليل الأرض', total_slides=5)
        self.assertNotIn('مشروع متعدد الاستخدامات', cleaned)
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'تحليل الأرض', 'type': 'content', 'section_key': 'land',
             'bullets': ['المحتوى المعتمد لهذا القسم', 'التفاصيل المتاحة في بيانات المشروع',
                         'الملخص النهائي دون تكرار']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, {'project_name': 'المشروع', 'land_and_building_summary': 'الملخص المعتمد'}, {})
        land = [slide for slide in plan['slides']
                if slide.get('section_key') == 'land' and slide.get('type') == 'content']
        self.assertEqual(len(land), 1, land)
        self.assertEqual(land[0].get('content_source'), 'land_and_building_summary')

    def test_component_plan_keeps_every_row_and_selected_values(self):
        engine = self.application_module.slide_engine
        components = [{
            'name': f'المكون {index}', 'useType': 'hospitality' if index % 2 else 'retail',
            'units': index, 'unitArea': index * 10, 'builtArea': index * 100,
            'revenueArea': index * 80, 'investmentModel': 'dailyRent' if index % 2 else 'sale',
        } for index in range(1, 15)]
        project = {'project_name': 'المشروع', 'financial_study_model': {
            'inputs': {'projectCost': 1000000}, 'dynamicRows': {'components': components},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '3. مكونات المشروع'},
                {'type': 'table', 'headers': ['اسم المكون', 'نوع الاستخدام', 'عدد الوحدات', 'نموذج الاستفادة'],
                 'rows': [['', 'تجاري ترفيهي خدمات مواقف سكني فندقي', '',
                           'بيع وحدات إيجار يومي إيجار شهري إيجار سنوي']]},
            ]},
        }}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        slides = [slide for slide in plan['slides']
                  if str(slide.get('content_source') or '').startswith('project_components:')]
        self.assertEqual([slide['content_source'] for slide in slides],
                         ['project_components:0:6', 'project_components:6:12', 'project_components:12:14'])
        notes = '\n'.join(engine._slide_source_data_note(slide, project) for slide in slides)
        for index in range(1, 15):
            self.assertIn(f'المكون {index}', notes)
        self.assertIn('إيجار يومي', notes)
        self.assertIn('بيع وحدات', notes)
        self.assertNotIn('تجاري ترفيهي خدمات مواقف', notes)
        index_source = read_frontend_text()
        self.assertIn("control.selectedOptions?.[0]", index_source)
        self.assertNotIn("control.type !== 'hidden' && !control.disabled", index_source)
        self.assertNotIn("el.type === 'file' || el.type === 'hidden' || el.disabled", index_source)
        self.assertIn("el.closest('.dynamic-off,.conditional-off,.hidden,[hidden]')", index_source)
        self.assertIn('const compatibleComponents = parseStoredProjectTable(source.project_components_data);', index_source)

    def test_component_slide_retries_when_a_required_component_is_missing(self):
        engine = self.application_module.slide_engine
        project = {'financial_study_model': {'inputs': {'projectCost': 1}, 'dynamicRows': {'components': [
            {'name': 'الفندق', 'investmentModel': 'dailyRent'},
            {'name': 'المطاعم', 'investmentModel': 'annualRent'},
        ]}}}
        responses = iter([
            '<div class="slide" style="background:#fff;color:#111"><p>الفندق</p></div>',
            '<div class="slide" style="background:#fff;color:#111"><p>الفندق</p><p>المطاعم</p></div>',
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'مكونات المشروع', 'type': 'content',
                       'content_source': 'project_components:0:2'},
            3, 5, {'primary_color': '#123456'}, generated, project_data=project)
        self.assertIn('المطاعم', html)
        self.assertEqual(len(prompts), 2)
        self.assertIn('المطاعم', prompts[1])

    def test_financial_summary_uses_pdf_report_and_varied_chart_types(self):
        engine = self.application_module.slide_engine
        report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
            {'type': 'heading', 'level': 3, 'text': 'التكاليف والاستثمار'},
            {'type': 'fields', 'rows': [['إجمالي تكلفة الاستثمار', '1,234,567'], ['قيمة التسهيل', '500,000']]},
            {'type': 'heading', 'level': 3, 'text': 'مؤشرات العائد والاسترداد'},
            {'type': 'fields', 'rows': [['ROI', '18.25%'], ['فترة الاسترداد', '6.5 سنة']]},
            {'type': 'heading', 'level': 2, 'text': 'الإيرادات السنوية'},
            {'type': 'table', 'headers': ['السنة', 'الإيراد'], 'rows': [['2027', '100'], ['2028', '150']]},
            {'type': 'heading', 'level': 2, 'text': 'هيكل التكاليف'},
            {'type': 'table', 'headers': ['البند', 'القيمة'], 'rows': [['تنفيذ', '70'], ['تصميم', '30']]},
            {'type': 'heading', 'level': 2, 'text': 'التدفقات النقدية السنوية'},
            {'type': 'table', 'headers': ['السنة', 'التدفق'], 'rows': [['2027', '-50'], ['2028', '80']]},
            {'type': 'heading', 'level': 2, 'text': 'تحليل الحساسية'},
            {'type': 'table', 'headers': ['السيناريو', 'ROI'], 'rows': [['متحفظ', '12%'], ['أساسي', '18%']]},
        ]}
        project = {'project_name': 'المشروع', 'financial_study_model': {
            'inputs': {'projectCost': 1234567}, 'report': report,
        }}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        financial = [slide for slide in plan['slides']
                     if slide.get('section_key') == 'financial' and slide.get('type') == 'content']
        summaries = [slide for slide in financial
                     if str(slide.get('content_source') or '').startswith('financial_summary:')]
        summary_note = '\n'.join(engine._slide_source_data_note(slide, project) for slide in summaries)
        for value in ('التكاليف والاستثمار', '1,234,567', 'مؤشرات العائد والاسترداد', '18.25%', '6.5 سنة'):
            self.assertIn(value, summary_note)
        self.assertEqual(financial[-len(summaries):], summaries)
        chart_types = {slide.get('chart_type') for slide in financial if slide.get('chart_type')}
        self.assertEqual(chart_types, {'waterfall', 'combo', 'heatmap'})
        self.assertEqual(set(engine.FINANCIAL_CHART_TYPES), {'waterfall', 'combo', 'heatmap'})
        self.assertEqual(set(engine.APPROVED_CHART_TYPES), {'horizontal_bar', 'waterfall', 'combo', 'heatmap'})
        chart_slide = next(slide for slide in financial if slide.get('chart_type') == 'waterfall')
        self.assertIn('نوع الرسم المطلوب: waterfall', engine.build_slide_user_msg(
            chart_slide, 3, len(plan['slides']), {}, project))

    def test_strictly_four_approved_chart_types_in_four_locations(self):
        engine = self.application_module.slide_engine
        # Verify only 4 approved chart types exist
        self.assertEqual(engine.APPROVED_CHART_TYPES, ('horizontal_bar', 'waterfall', 'combo', 'heatmap'))
        self.assertEqual(engine.FINANCIAL_CHART_TYPES, ('waterfall', 'combo', 'heatmap'))

        # 1. Market Study: Competitor comparison gets horizontal_bar
        project_market = {
            'project_name': 'مشروع تجريبي',
            'market_study_data': {
                'competitors': [
                    {'name': 'منافس أ', 'price_value': '1500', 'price_type': 'سعر المتر بيع'},
                    {'name': 'منافس ب', 'price_from': '1200', 'price_to': '1800', 'price_type': 'سعر المتر بيع'},
                ]
            }
        }
        plan_market = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project_market, {})
        market_slides = [s for s in plan_market['slides'] if s.get('section_key') == 'market']
        comp_slide = next((s for s in market_slides if s.get('content_source') == 'market_study_data.competitors'), None)
        self.assertIsNotNone(comp_slide)
        self.assertEqual(comp_slide.get('chart_type'), 'horizontal_bar')
        self.assertEqual(comp_slide.get('design_style'), 'chart')
        msg = engine.build_slide_user_msg(comp_slide, 3, 5, {'primary_color': '#123456'}, project_market)
        self.assertIn('نوع الرسم المطلوب: horizontal_bar', msg)
        self.assertIn('مخطط الأعمدة الأفقية', msg)

        # 2. Financial Study: Cost -> waterfall, Cashflow -> combo, Sensitivity -> heatmap
        report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
            {'type': 'heading', 'level': 2, 'text': 'هيكل التكاليف والاستثمار'},
            {'type': 'table', 'headers': ['البند', 'القيمة'], 'rows': [['تطوير', '100'], ['أرض', '200']]},
            {'type': 'heading', 'level': 2, 'text': 'التدفقات النقدية السنوية'},
            {'type': 'table', 'headers': ['السنة', 'التدفق'], 'rows': [['2027', '-50'], ['2028', '80']]},
            {'type': 'heading', 'level': 2, 'text': 'مقارنة السيناريوهات المالية'},
            {'type': 'table', 'headers': ['السيناريو', 'ROI'], 'rows': [['متحفظ', '12%'], ['أساسي', '18%']]},
            {'type': 'heading', 'level': 2, 'text': 'بنود الإيرادات'},
            {'type': 'table', 'headers': ['السنة', 'الإيراد'], 'rows': [['2027', '100'], ['2028', '150']]},
        ]}
        project_fin = {'project_name': 'مشروع مالي', 'financial_study_model': {'inputs': {'projectCost': 1000}, 'report': report}}
        plan_fin = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project_fin, {})
        fin_slides = [s for s in plan_fin['slides'] if s.get('section_key') == 'financial']
        fin_charts = {s.get('chart_type') for s in fin_slides if s.get('chart_type')}
        self.assertEqual(fin_charts, {'waterfall', 'combo', 'heatmap'})
        # Revenue table should NOT have a chart
        rev_slide = next(s for s in fin_slides if 'إيراد' in s.get('title', ''))
        self.assertEqual(rev_slide.get('chart_type'), '')
        self.assertEqual(rev_slide.get('design_style'), 'table')

        # 3. Any chart outside the 4 locations/types is strictly stripped
        raw_disallowed = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مخطط كعكة للمكونات', 'type': 'content', 'section_key': 'components',
             'design_style': 'chart', 'chart_type': 'pie', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'مخطط تدفق الموقع', 'type': 'content', 'section_key': 'location',
             'design_style': 'chart', 'chart_type': 'donut', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan_disallowed = engine.normalize_presentation_plan(raw_disallowed, {'project_name': 'س'}, {})
        disallowed_slides = [s for s in plan_disallowed['slides'] if s.get('section_key') in ('components', 'location')]
        for s in disallowed_slides:
            self.assertEqual(s.get('chart_type'), '')
            self.assertNotEqual(s.get('design_style'), 'chart')

    def test_market_section_is_complete_fixed_table_one_chart_and_media_free(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع السوق',
            'market_study_data': json.dumps({
                'competitor_radius': '10',
                'data_period': '12m',
                'competitors': [{
                    'name': 'منافس موثق', 'price_value': '15000',
                    'price_type': 'سعر المتر المربع', 'operation_type': 'بيع',
                    'logo_url': '/uploads/competitor.png', 'source': 'مصدر رسمي',
                    'data_date': '2026-01',
                }],
                'summary': {
                    'market_definition': 'تعريف السوق', 'city_position': 'وضع المدينة',
                    'sector_performance': 'أداء القطاع', 'supply': 'العرض',
                    'demand': 'الطلب', 'competition': 'المنافسة',
                    'market_gap': 'الفجوة السوقية', 'recommendation': 'التوصية',
                    'risks': 'المخاطر', 'decision': 'القرار',
                },
                'swot': {
                    'strengths': 'موقع قوي - مكونات متكاملة',
                    'weaknesses': 'تكلفة مرتفعة',
                    'opportunities': 'نمو الطلب',
                    'threats': 'منافسة جديدة',
                },
                'one_block_summary': 'ملخص دراسة السوق كامل',
                'sources': [{
                    'name': 'مصدر رسمي', 'url': 'https://example.test/source',
                    'data_date': '2026-01', 'accessed_at': '2026-02',
                    'reliability': '1', 'note': 'ملاحظة المصدر',
                }],
            }, ensure_ascii=False),
        }
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مقارنة المنافسين', 'type': 'map_catchment'},
            {'title': 'الفجوة السوقية', 'type': 'map_overview'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        market = [slide for slide in plan['slides'] if slide.get('section_key') == 'market']
        content = [slide for slide in market if slide.get('type') == 'content']
        self.assertEqual(sum(1 for slide in content if slide.get('chart_type')), 1)
        self.assertTrue(any(slide.get('content_source') == 'market_study_data.scope' for slide in content))
        self.assertTrue(any(str(slide.get('content_source') or '').startswith('market_study_data.summary') for slide in content))
        self.assertTrue(any(str(slide.get('content_source') or '').startswith('market_study_data.one_block_summary') for slide in content))
        self.assertTrue(any(str(slide.get('content_source') or '').startswith('market_study_data.sources') for slide in content))
        self.assertEqual(sum(1 for slide in content if slide.get('content_source') == 'market_study_data.summary'), 1)
        summary_pages = [slide for slide in content
                         if str(slide.get('content_source') or '').startswith('market_study_data.summary')]
        covered = set()
        for slide in summary_pages:
            covered.update(range(int(slide.get('market_row_start') or 0),
                                 int(slide.get('market_row_end') or 0)))
        market_data = json.loads(project['market_study_data'])
        self.assertEqual(covered, set(range(len(engine._market_summary_rows(market_data)))))
        self.assertLessEqual(sum(1 for slide in content if str(slide.get('content_source') or '').startswith('market_study_data.one_block_summary')), 2)
        self.assertEqual(sum(1 for slide in content if slide.get('content_source') == 'market_study_data.sources'), 1)
        self.assertTrue(all(not slide.get('image_tokens') and not slide.get('requires_image') for slide in market))

        swot = [slide for slide in plan['slides']
                if slide.get('section_key') == 'swot_risks' and slide.get('type') == 'content']
        self.assertEqual(len(swot), 2)
        swot_slide = next(slide for slide in swot if slide.get('content_source') == 'market_study_data.swot')
        risk_slide = next(slide for slide in swot if slide.get('content_source') == 'market_study_data.summary.risks')
        swot_html = engine.generate_single_slide(
            'system', swot_slide, 3, 10, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('SWOT must be deterministic'),
            project_data=project,
        )
        for value in ('نقاط القوة', 'نقاط الضعف', 'الفرص', 'التهديدات', 'موقع قوي', 'منافسة جديدة'):
            self.assertIn(value, swot_html)
        self.assertNotIn('"strengths"', swot_html)

        rendered = []
        for slide in content:
            html = engine.generate_single_slide(
                'system', slide, 3, 10, {'primary_color': '#123456'},
                lambda *_args, **_kwargs: self.fail('market data slides must be deterministic'),
                project_data=project,
            )
            rendered.append((slide, html))
        self.assertTrue(all('MAP_' not in html for _slide, html in rendered))
        for slide, html in rendered:
            if slide.get('content_source') == 'market_study_data.competitors':
                continue
            image_tags = re.findall(r'<img\b[^>]*>', html, flags=re.IGNORECASE)
            self.assertTrue(
                all('presentation-chrome-logo' in tag for tag in image_tags),
                f'Only the fixed presentation chrome may contain images: {image_tags}',
            )
        competitor_html = next(html for slide, html in rendered
                               if slide.get('content_source') == 'market_study_data.competitors')
        self.assertIn('data-competitor-table', competitor_html)
        self.assertIn('##COMPETITOR_LOGO_1##', competitor_html)
        risk_html = engine.generate_single_slide(
            'system', risk_slide, 4, 10, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('risk analysis must be deterministic'),
            project_data=project,
        )
        self.assertIn('data-risk-register', risk_html)
        self.assertIn('المخاطر', risk_html)

        long_market = {
            'market_study_data': {
                'one_block_summary': (
                    'نطاق دراسة السوق\\n\\n'
                    + ('بيانات سوق العمل كاملة ومعتمدة كما وردت في الدراسة. ' * 150)
                    + '\\n\\nالنهاية الكاملة لملخص سوق العمل.'
                ),
            },
        }
        long_plan = engine.normalize_presentation_plan(
            {'slides': [
                {'title': 'الغلاف', 'type': 'cover'},
                {'title': 'الخاتمة', 'type': 'closing'},
            ]},
            long_market,
            {},
        )
        long_work_slides = [slide for slide in long_plan['slides']
                            if slide.get('content_source', '').startswith('market_study_data.one_block_summary:')]
        self.assertEqual(len(long_work_slides), 2)
        long_work_html = ''.join(
            engine.generate_single_slide(
                'system', slide, index + 1, 2, {'primary_color': '#123456'},
                lambda *_args, **_kwargs: self.fail('long market summary must be deterministic'),
                project_data=long_market,
            )
            for index, slide in enumerate(long_work_slides)
        )
        self.assertIn('النهاية الكاملة لملخص سوق العمل', long_work_html)
        self.assertIn('data-market-work-summary', long_work_html)
        self.assertIn('<p style=', long_work_html)
        self.assertNotIn('<article', long_work_html)

    def test_competitor_slides_hold_four_and_mixed_units_stay_in_chart(self):
        engine = self.application_module.slide_engine
        competitors = [
            {'name': 'منافس أ', 'operation_type': 'بيع', 'price_type': 'سعر المتر المربع',
             'price_value': '30000', 'status': 'قائم'},
            {'name': 'منافس ب', 'operation_type': 'بيع', 'price_type': 'سعر المتر المربع',
             'price_value': '28000', 'status': 'قائم'},
            {'name': 'منافس ج', 'operation_type': 'بيع', 'price_type': 'سعر المتر المربع',
             'price_value': '38000', 'status': 'قائم'},
            {'name': 'منافس د', 'operation_type': 'بيع', 'price_type': 'سعر المتر المربع',
             'price_value': '25000', 'status': 'تحت الإنشاء'},
            {'name': 'منافس هـ', 'operation_type': 'إيجار', 'price_type': 'إيجار سنوي',
             'price_value': '95000', 'status': 'قائم'},
        ]
        project = {'project_name': 'مشروع السوق', 'market_study_data': {'competitors': competitors}}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        comp_slides = [slide for slide in plan['slides']
                       if str(slide.get('content_source') or '').startswith('market_study_data.competitors')]
        # At most four competitors per slide: 5 split into balanced 3+2 pages.
        self.assertEqual(len(comp_slides), 2)
        self.assertEqual((comp_slides[0].get('competitor_start'), comp_slides[0].get('competitor_end')), (0, 3))
        self.assertEqual((comp_slides[1].get('competitor_start'), comp_slides[1].get('competitor_end')), (3, 5))
        html_1 = engine._build_sol_horizontal_bar_slide(
            comp_slides[0], project, {'primary_color': '#123456'}, slide_num=3, total_slides=8)
        for name in ('منافس أ', 'منافس ب', 'منافس ج'):
            self.assertIn(name, html_1)
        self.assertNotIn('منافس د', html_1)
        self.assertNotIn('منافس هـ', html_1)
        # Page 2 holds the sale+rent pair: mixed price units stay in the
        # chart as separately labelled sections.
        html_2 = engine._build_sol_horizontal_bar_slide(
            comp_slides[1], project, {'primary_color': '#123456'}, slide_num=4, total_slides=8)
        self.assertIn('منافس د', html_2)
        self.assertIn('منافس هـ', html_2)
        self.assertIn('مشاريع البيع', html_2)
        self.assertIn('مشاريع الإيجار', html_2)
        items = engine._extract_competitor_chart_data(competitors, project)
        chart_names = {item.get('name') for item in items}
        self.assertEqual(chart_names, {'منافس أ', 'منافس ب', 'منافس ج', 'منافس د', 'منافس هـ'})

    def test_market_summary_pagination_follows_text_volume(self):
        engine = self.application_module.slide_engine
        long_text = 'نص تحليلي معتمد طويل يغطي المحور بالكامل مع أرقام ومؤشرات السوق. ' * 8
        summary = {key: long_text for key in (
            'market_definition', 'city_position', 'sector_performance', 'supply', 'demand',
            'competition', 'market_gap', 'project_evaluation', 'recommendation', 'risks')}
        project = {'project_name': 'مشروع السوق', 'market_study_data': {'summary': summary}}
        market = engine._market_state(project)
        pages = engine._market_summary_pages(market)
        self.assertGreaterEqual(len(pages), 3)
        self.assertEqual(sum(len(page_rows) for _start, page_rows in pages), 10)
        starts = [start for start, _rows in pages]
        self.assertEqual(starts[0], 0)
        self.assertTrue(all(starts[i] < starts[i + 1] for i in range(len(starts) - 1)))

    def test_market_analysis_points_and_work_summary_paragraph_are_separate(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع السوق',
            'market_study_data': json.dumps({
                'competitor_radius': '10',
                'data_period': '12m',
                'competitors': [{
                    'name': 'منافس موثق', 'price_value': '15000',
                    'price_type': 'سعر المتر المربع', 'operation_type': 'بيع',
                }],
                'summary': {
                    'market_definition': 'قطاع الضيافة الفاخرة في جدة',
                    'city_position': 'تستفيد جدة من الطلب السياحي والأعمال',
                    'competition': 'المنافسة مباشرة مع مشاريع الواجهة البحرية',
                    'recommendation': 'التطوير مناسب مع مشغل عالمي',
                },
                'swot': {
                    'strengths': 'موقع قوي',
                    'weaknesses': 'تكلفة مرتفعة',
                    'opportunities': 'نمو الطلب',
                    'threats': 'منافسة جديدة',
                },
                'one_block_summary': 'يظهر السوق في جدة فرصة لتطوير مشروع ضيافة فاخر متكامل، مدعومة بموقع الواجهة البحرية وتنوع الطلب السياحي والأعمال، مع ضرورة التميز أمام المنافسين واستقطاب مشغل عالمي وإدارة التكلفة والتسويق على مراحل.',
                'sources': [{'name': 'مصدر رسمي', 'url': 'https://example.test/source'}],
            }, ensure_ascii=False),
        }
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مقارنة المنافسين', 'type': 'map_catchment'},
            {'title': 'الفجوة السوقية', 'type': 'map_overview'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        content = [slide for slide in plan['slides']
                   if slide.get('section_key') == 'market' and slide.get('type') == 'content']
        summary_slides = [slide for slide in content
                          if slide.get('content_source') == 'market_study_data.summary']
        self.assertEqual(len(summary_slides), 1)
        html = engine.generate_single_slide(
            'system', summary_slides[0], 3, 10, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('market summary must be deterministic'),
            project_data=project,
        )
        self.assertIn('قطاع الضيافة الفاخرة في جدة', html)
        self.assertIn('تعريف السوق', html)
        self.assertIn('المنافسة مباشرة مع مشاريع الواجهة البحرية', html)
        self.assertIn('تحليل السوق', html)
        self.assertNotIn('الملخص التنفيذي لسوق المشروع', html)
        work_slide = next(slide for slide in content
                          if slide.get('content_source') == 'market_study_data.one_block_summary')
        work_html = engine.generate_single_slide(
            'system', work_slide, 4, 10, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: self.fail('market work summary must be deterministic'),
            project_data=project,
        )
        self.assertIn('يظهر السوق في جدة فرصة لتطوير مشروع ضيافة فاخر متكامل', work_html)
        self.assertIn('<p style=', work_html)
        self.assertNotIn('<article', work_html)
        self.assertNotIn('grid-template-areas', work_html)
        self.assertNotIn('grid-area:aside', work_html)
        facts = engine._market_study_facts(project)
        self.assertIn('### الملخص التنفيذي لسوق المشروع', facts)
        self.assertIn('### تحليل السوق', facts)
        self.assertIn('يظهر السوق في جدة فرصة لتطوير مشروع ضيافة فاخر متكامل', facts)

    def test_wide_cashflow_table_in_report_preserves_combo_chart(self):
        engine = self.application_module.slide_engine
        headers = ['البيان'] + [f'سنة {i}' for i in range(1, 16)] + ['الإجمالي']
        rows = [
            ['صافي تدفق المشروع'] + [str((i - 3) * 10000000) for i in range(1, 16)] + ['750000000'],
            ['الرصيد التراكمي'] + [str((i - 5) * 20000000) for i in range(1, 16)] + ['1500000000'],
        ]
        report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
            {'type': 'heading', 'level': 2, 'text': 'جدول التدفقات النقدية'},
            {'type': 'table', 'headers': headers, 'rows': rows},
        ]}
        project = {'project_name': 'مشروع تدفقات', 'financial_study_model': {'inputs': {'projectCost': 50000000}, 'report': report}}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        fin_slides = [s for s in plan['slides'] if s.get('section_key') == 'financial']
        combo_slides = [s for s in fin_slides if s.get('chart_type') == 'combo']
        self.assertEqual(len(combo_slides), 1, "Expected exactly 1 combo chart slide for cash flow")
        combo_slide = combo_slides[0]
        self.assertEqual(combo_slide.get('design_style'), 'chart')
        self.assertIn('التدفقات النقدية', combo_slide.get('title', ''))
        c_data = engine._extract_combo_chart_data(None, project['financial_study_model'], project)
        self.assertGreaterEqual(len(c_data['items']), 5)
        fb_headers, fb_rows = engine._fallback_table_data(combo_slide, project)
        self.assertEqual(fb_headers, ['السنة', 'صافي التدفق السنوي', 'الرصيد التراكمي'])
        self.assertEqual(len(fb_rows), len(c_data['items']))

    def test_waterfall_mandatory_developer_fund_finance_costs(self):
        engine = self.application_module.slide_engine
        cost_rows = [
            {'اسم التكلفة': 'أعمال إنشائية', 'الناتج': '100,000,000'},
            {'اسم التكلفة': 'تصاميم ودراسات', 'الناتج': '10,000,000'}
        ]
        model = {
            'inputs': {
                'developerCostValue': '8,000,000',
                'fundFeesTotal': '4,500,000',
                'financeInterestTotal': '12,000,000',
                'arrangementFeeTotal': '1,000,000',
            },
            'tables': {
                'costTable': cost_rows
            }
        }
        res = engine._extract_waterfall_chart_data({'rows': cost_rows}, model=model)
        names = [it['name'] for it in res['items']]
        self.assertIn('أعمال إنشائية', names)
        self.assertIn('تصاميم ودراسات', names)
        self.assertIn('تكلفة المطور', names)
        self.assertIn('تكلفة الصندوق', names)
        self.assertIn('تكلفة التمويل', names)

        dev_item = next(it for it in res['items'] if it['name'] == 'تكلفة المطور')
        fund_item = next(it for it in res['items'] if it['name'] == 'تكلفة الصندوق')
        fin_item = next(it for it in res['items'] if it['name'] == 'تكلفة التمويل')
        self.assertEqual(dev_item['value_sar'], 8000000.0)
        self.assertEqual(fund_item['value_sar'], 4500000.0)
        self.assertEqual(fin_item['value_sar'], 13000000.0)

        # Total check: 100M + 10M + 8M + 4.5M + 13M = 135.5M
        self.assertEqual(res['total']['value_sar'], 135500000.0)
        self.assertEqual(res['total']['name'], 'إجمالي تكلفة المشروع')
        self.assertIn('svg_code', res.get('summary', {}))

        # Test omission when 0 or not present
        zero_model = {
            'inputs': {
                'developerCostValue': '0',
                'fundFeesTotal': 0,
                'totalFinanceCost': 0,
            },
            'tables': {'costTable': cost_rows}
        }
        res_zero = engine._extract_waterfall_chart_data({'rows': cost_rows}, model=zero_model)
        names_zero = [it['name'] for it in res_zero['items']]
        self.assertNotIn('تكلفة المطور', names_zero)
        self.assertNotIn('تكلفة الصندوق', names_zero)
        self.assertNotIn('تكلفة التمويل', names_zero)
        self.assertEqual(res_zero['total']['value_sar'], 110000000.0)

    def test_financial_study_slides_strictly_follow_pdf_table_design(self):
        engine = self.application_module.slide_engine
        import design_templates as templates

        # 1. Test _balanced_row_ranges prevents 1-row orphan slides
        self.assertEqual(engine._balanced_row_ranges(0), [])
        self.assertEqual(engine._balanced_row_ranges(8), [(0, 8)])
        self.assertEqual(engine._balanced_row_ranges(12), [(0, 12)])
        ranges_13 = engine._balanced_row_ranges(13)
        self.assertEqual(len(ranges_13), 2)
        for start, end in ranges_13:
            self.assertGreaterEqual(end - start, 4)  # No 1-2 row chunks
        self.assertEqual(ranges_13, [(0, 7), (7, 13)])

        # 2. Test plan normalization packs a narrow 13-row table on one slide
        # instead of burning two slides, while wide tables still split evenly.
        report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'جدول تكاليف الاستثمار المفصل'},
            {'type': 'table', 'headers': ['البند', 'القيمة'], 'rows': [[f'بند {i}', f'{i * 1000}'] for i in range(1, 14)]},
        ]}
        project = {'project_name': 'مشروع متوازن', 'financial_study_model': {'inputs': {'projectCost': 1000}, 'report': report}}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        fin_slides = [s for s in plan['slides'] if s.get('section_key') == 'financial' and 'تكاليف الاستثمار المفصل' in s.get('title', '')]
        self.assertEqual(len(fin_slides), 1)
        self.assertEqual([s.get('row_count') for s in fin_slides], [13])

        # Genuinely long narrow tables still split into balanced slides.
        long_report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'جدول تكاليف الاستثمار المفصل'},
            {'type': 'table', 'headers': ['البند', 'القيمة'], 'rows': [[f'بند {i}', f'{i * 1000}'] for i in range(1, 21)]},
        ]}
        long_project = {'project_name': 'مشروع متوازن', 'financial_study_model': {'inputs': {'projectCost': 1000}, 'report': long_report}}
        long_plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الخاتمة', 'type': 'closing'},
        ]}, long_project, {})
        long_slides = [s for s in long_plan['slides'] if s.get('section_key') == 'financial' and 'تكاليف الاستثمار المفصل' in s.get('title', '')]
        self.assertEqual([s.get('row_count') for s in long_slides], [10, 10])

        # Wide tables keep the tighter budget and split evenly without orphans.
        wide_report = {'parts': [
            {'type': 'heading', 'level': 2, 'text': 'جدول تكاليف الاستثمار المفصل'},
            {'type': 'table', 'headers': ['البند', 'سنة 1', 'سنة 2', 'سنة 3', 'سنة 4', 'الإجمالي'],
             'rows': [[f'بند {i}', '1', '2', '3', '4', '10'] for i in range(1, 14)]},
        ]}
        wide_project = {'project_name': 'مشروع متوازن', 'financial_study_model': {'inputs': {'projectCost': 1000}, 'report': wide_report}}
        wide_plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الخاتمة', 'type': 'closing'},
        ]}, wide_project, {})
        wide_slides = [s for s in wide_plan['slides'] if s.get('section_key') == 'financial' and 'تكاليف الاستثمار المفصل' in s.get('title', '')]
        self.assertEqual([s.get('row_count') for s in wide_slides], [7, 6])

        # 3. Test prompt user message carries strict PDF table instructions and bans card/box grids
        fin_table_slide = fin_slides[0]
        msg = engine.build_slide_user_msg(fin_table_slide, 3, 5, {'primary_color': '#2a52be'}, project)
        self.assertIn('تصميم جداول تقرير PDF المالي هو التصميم الأساسي والإلزامي', msg)
        self.assertIn('ممنوع منعاً باتاً: تحويل الجداول المالية إلى كروت عائمة (cards)', msg)
        self.assertIn('summary-table', msg)

        # 4. Test design rules carry PDF table layout specification
        rules = templates.build_design_rules({'primary_color': '#2a52be'})
        self.assertIn('تصميم جداول الدراسة المالية (مستوحى من تقرير PDF المالي المنظم)', rules)
        self.assertIn('ممنوع منعاً باتاً تحويل جداول الدراسة المالية إلى كروت عائمة', rules)

    def test_section_presentation_plan_keeps_only_the_requested_section_and_shell(self):
        engine = self.application_module.slide_engine
        project = {'project_name': 'مشروع الاختبار', 'financial_study_model': {
            'inputs': {'projectCost': 1234567},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'الإيرادات السنوية'},
                {'type': 'table', 'headers': ['السنة', 'الإيراد'],
                 'rows': [['2027', '100'], ['2028', '150']]},
            ]},
        }}
        full_plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'نبذة', 'type': 'content', 'section_key': 'overview',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})

        filtered = engine.filter_presentation_plan_sections(full_plan, ('financial',))
        self.assertIsNotNone(filtered)
        self.assertEqual(
            {slide.get('section_key') for slide in filtered['slides']},
            {'cover', 'index', 'financial', 'closing'},
        )
        self.assertEqual(filtered['slides'][0]['type'], 'cover')
        self.assertEqual(filtered['slides'][1]['type'], 'index')
        self.assertEqual(filtered['slides'][-1]['type'], 'closing')
        self.assertTrue(any(slide.get('content_source', '').startswith('financial_report:')
                            for slide in filtered['slides']))
        self.assertEqual(
            [entry['section_key'] for entry in filtered['slides'][1]['index_entries']],
            ['financial', 'closing'],
        )
        self.assertIsNone(engine.filter_presentation_plan_sections(full_plan, ('team',)))

    def test_financial_section_presentation_api_ignores_full_deck_minimum_and_frontend_saves_it(self):
        project = {'project_name': 'مشروع الاختبار', 'financial_study_model': {
            'inputs': {'projectCost': 1234567},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'الإيرادات السنوية'},
                {'type': 'table', 'headers': ['السنة', 'الإيراد'],
                 'rows': [['2027', '100'], ['2028', '150']]},
            ]},
        }}
        planner = json.dumps({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'نبذة', 'type': 'content', 'section_key': 'overview',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الدراسة المالية', 'type': 'content', 'section_key': 'financial',
             'content_source': 'financial_indicators'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, ensure_ascii=False)
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat_parallel', return_value={
            'choices': [{'message': {'content': planner}}]
        }):
            response = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
                'projectData': project,
                'sectionKey': 'section-financial-calc',
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload['success'])
        slides = payload['plan']['slides']
        self.assertLess(len(slides), 14)
        self.assertEqual(
            {slide.get('section_key') for slide in slides},
            {'cover', 'index', 'financial', 'closing'},
        )
        with self.app.app_context(), patch.object(
                self.application_module, 'call_zai_chat_parallel', return_value={
                    'choices': [{'message': {'content': planner}}]
                }):
            branding = dict(db.get_branding(self.tenant_a) or {})
            branding.update({'lock_slide_count': 1, 'default_slide_count': 30, 'min_slides': 30})
            locked_payload = self.application_module._execute_slide_plan(
                project, self.tenant_a, branding, target_section_keys=('financial',))
        self.assertTrue(locked_payload['success'])
        self.assertLess(len(locked_payload['plan']['slides']), 30)

        invalid = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
            'projectData': project,
            'sectionKey': 'unknown-section',
        })
        self.assertEqual(invalid.status_code, 400)

        index_source = read_frontend_text()
        self.assertIn("generateButton.textContent = 'توليد عرض القسم'", index_source)
        self.assertIn('async function generateProjectSectionPresentation(sectionKey, sectionLabel = \'\')', index_source)
        self.assertIn('if (sectionKey) requestBody.sectionKey = sectionKey;', index_source)
        self.assertIn('requestBody.presentationId = tenantPresentationId;', index_source)
        self.assertIn('requestBody.projectData = payload;', index_source)
        self.assertIn('tenantPresentationId = null;', index_source)
        self.assertIn("api('POST', '/api/presentations'", index_source)
        self.assertIn('await saveTenantPresentation(options.presentationTitle)', index_source)
        self.assertIn('tenantPresentationTitle = p.title || \'\';', index_source)
        self.assertIn('if (options.markDraftDirty !== false) triggerAutoSaveDraft();', index_source)
        self.assertIn("hasLocation && (!sectionKey || sectionKey === 'location')", index_source)

    def test_wide_financial_tables_split_columns_and_skip_broken_charts(self):
        engine = self.application_module.slide_engine
        headers = ['السنة'] + [f'المؤشر {index}' for index in range(1, 13)]
        rows = [['9'] + [str(index * 100) for index in range(1, 13)],
                ['10'] + [str(index * 200) for index in range(1, 13)]]
        project = {'financial_study_model': {
            'inputs': {'projectCost': 1},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'جدول التدفقات النقدية'},
                {'type': 'table', 'headers': headers, 'rows': rows},
            ]},
        }}
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        slides = [slide for slide in plan['slides']
                  if str(slide.get('content_source') or '').startswith('financial_report:1:')]
        self.assertEqual(len(slides), 1, slides)
        self.assertTrue(all(slide.get('design_style') == 'table' for slide in slides))
        for slide in slides:
            payload = json.loads(engine._slide_source_data_note(slide, project).split('\n', 1)[1])
            self.assertEqual(payload['headers'][0], 'السنة')
            self.assertTrue(all(len(row) == len(payload['headers']) for row in payload['rows']))

    def test_map_slide_uses_contain_without_crop(self):
        engine = self.application_module.slide_engine
        html = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><img src="##MAP_OVERVIEW##" '
            'style="width:52%;height:100%;object-fit:cover;object-position:right center"></div>',
            'map_overview', {}, {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
            slide_num=3, slide_title='الموقع', total_slides=5)
        map_tag = next(tag for tag in re.findall(r'<img\b[^>]*>', html)
                       if '/uploads/maps/overview.png' in tag)
        self.assertIn('object-fit:contain!important', map_tag)
        self.assertIn('object-position:center center!important', map_tag)
        self.assertNotIn('object-fit:cover', map_tag)
        self.assertNotIn('object-position:right', map_tag)

    def test_build_commit_falls_back_to_deployment_marker(self):
        module = self.application_module
        marker = Path(self.temp_dir.name) / '.deployed-commit-test'
        marker.write_text(json.dumps({'commit': 'abcdef1234567890', 'source': 'github'}), encoding='utf-8')
        with patch.object(module, 'DEPLOYMENT_MARKER_PATH', str(marker)), \
                patch.object(module.subprocess, 'check_output', side_effect=OSError('no git')):
            module._BUILD_COMMIT = None
            self.assertEqual(module._build_commit(), 'abcdef1')
        module._BUILD_COMMIT = None

    def test_media_manifest_carries_land_descriptions_and_keeps_team_logos(self):
        project = {
            'team_selection': json.dumps({'local': [{
                'name': 'المصمم', 'role': 'التصميم', 'logoFileId': 'team-file',
            }], 'excluded': [], 'roles': {}}, ensure_ascii=False),
            'land_photos_file_meta': [{
                'id': 'land-file', 'originalName': 'land.jpg', 'description': 'الشارع الشمالي',
            }],
        }
        with patch.object(self.application_module, '_generation_project_image_url',
                          side_effect=lambda _tenant, file_id: '/uploads/creative/' + file_id + '.jpg'):
            augmented = self.application_module._augment_generation_images({}, project, self.tenant_a)
        self.assertEqual(augmented['team_members'][0]['logo'], '/uploads/creative/team-file.jpg')
        self.assertEqual(augmented['land_photos'][0]['url'], '/uploads/creative/land-file.jpg')
        self.assertEqual(augmented['land_photos'][0]['description'], 'الشارع الشمالي')

        images = {
            'cover': '/uploads/creative/cover.jpg',
            'moodboard': ['/uploads/creative/right.jpg'],
            'moodboard_meta': [{'label': 'الواجهة اليمنى', 'caption': 'تفاصيل الواجهة'}],
            'land_photos': [{'url': '/uploads/creative/land.jpg',
                             'name': 'صورة الأرض', 'description': 'الشارع الشمالي'}],
            'plans': ['/uploads/creative/plan.jpg'],
            'plan_meta': [{'title': 'المخطط العام', 'description': 'توزيع المشروع'}],
            'team_members': [{'name': 'المصمم', 'role': 'التصميم',
                              'logo': '/uploads/creative/team.jpg'}],
        }
        info = self.application_module._get_images_info(images, {'project_name': 'المشروع'})
        for expected in ('##MOODBOARD_IMAGE_1##', 'تفاصيل الواجهة', '##LAND_PHOTO_1##',
                         'الشارع الشمالي', '##PLAN_IMAGE_1##', 'توزيع المشروع',
                         '##TEAM_LOGO_1##'):
            self.assertIn(expected, info)

        html = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px">'
            '<img class="team-logo" src="##TEAM_LOGO_1##">'
            '<img src="##LAND_PHOTO_1##"></div>',
            'content', {'project_name': 'المشروع'},
            {'primary_color': '#123456', 'accent_color': '#abcdef'},
            creative_images=images, slide_num=3, slide_title='الوسائط', total_slides=5,
        )
        self.assertIn('/uploads/creative/team.jpg', html)
        self.assertIn('/uploads/creative/land.jpg', html)
        self.assertNotIn('##TEAM_LOGO_1##', html)
        self.assertNotIn('##LAND_PHOTO_1##', html)

    def test_slides_workspace_can_return_to_the_project_form_without_losing_it(self):
        """There was no way back from the slides page to بيانات المشروع: the only navigation was
        the dashboard, and from there "عرض جديد" calls startTenantProject(), which resets the
        state and shows a blank form as if the project were gone."""
        index_source = read_frontend_text()
        toolbar = index_source.split('<section id="tenantSlidesPage"')[1].split('</div>\n\n      <!-- Live')[0]
        self.assertIn("navigateTenantWorkflow('tenantProjectPage')", toolbar)
        self.assertIn('بيانات المشروع', toolbar)

        # Going back only shows the page again: it must not rebuild or reload the form, because the
        # rendered form already holds the hydrated values.
        nav = index_source.split('async function navigateTenantWorkflow(pageId) {')[1]
        nav = nav.split('\n    function ')[0]
        self.assertIn("if (pageId === 'tenantProjectPage') {\n        showTenantPage(pageId);", nav)
        self.assertNotIn('startTenantProject', nav)
        self.assertNotIn('loadTenantProjectForm', nav)

    def test_slides_page_can_regenerate_one_slide_without_rebuilding_the_deck(self):
        index_source = read_frontend_text()
        self.assertIn('إعادة توليد هذه الشريحة فقط', index_source)
        self.assertIn('async function regenerateTenantSlide(index)', index_source)
        replacement_body = index_source.split('async function generateTenantSlideFromSnapshot(snapshot, slideIndex, totalSlides, generationImages, current = {}) {', 1)[1]
        replacement_body = replacement_body.split('\n    async function generateTenantSlideReplacement(index, generationImages)', 1)[0]
        self.assertIn('slidePlan: { slides: [snapshot] }', replacement_body)
        regenerate_body = index_source.split('async function regenerateTenantSlide(index) {', 1)[1]
        regenerate_body = regenerate_body.split('\n    function buildPresentationGenerationImages()', 1)[0]
        self.assertIn('tenantSlidesData[context.slideIndex] =', regenerate_body)
        self.assertIn('triggerAutoSaveDraft();', regenerate_body)
        self.assertNotIn('await saveTenantPresentation()', regenerate_body)
        self.assertIn('لن تتأثر بقية الشرائح', regenerate_body)

    def test_designer_chat_can_regenerate_only_the_requested_section(self):
        index_source = read_frontend_text()
        self.assertIn('detectTenantSectionRegenerationRequest', index_source)
        self.assertIn(".replace(/ة/g, 'ه')", index_source)
        self.assertIn('تصميم|تنسيق', index_source)
        self.assertIn('const isSectionRebuildCommand', index_source)
        self.assertIn('setInlineLoaderProgress', index_source)
        self.assertNotIn('Math.min(92, pct +', index_source)
        self.assertIn('send the in-memory copy as the source for the next turn.', index_source)
        self.assertIn('if (tenantPresentationId) {', index_source)
        self.assertIn('async function regenerateTenantSection(sectionKey, sectionLabel)', index_source)
        section_body = index_source.split('async function regenerateTenantSection(sectionKey, sectionLabel) {', 1)[1]
        section_body = section_body.split('\n    function buildPresentationGenerationImages()', 1)[0]
        self.assertIn('requestTenantSectionSlidePlans', section_body)
        self.assertIn('const plannedSlides = sectionPlan.slides;', section_body)
        self.assertIn('const projectedTotal = tenantSlidesData.length - targetIndexes.length + plannedSlides.length;', section_body)
        self.assertIn('nextSlides.splice(firstIndex, 0, ...replacements.map(item => item.slide));', section_body)
        self.assertIn('generateTenantSlideFromSnapshot', section_body)
        self.assertIn('مع إبقاء باقي العرض كما هو', section_body)
        self.assertIn('لم يتم استبدال الشرائح القديمة', section_body)
        self.assertIn('triggerAutoSaveDraft();', section_body)
        self.assertNotIn('await saveTenantPresentation()', section_body)

        chat_body = index_source.split('async function sendTenantDesignerChat() {', 1)[1]
        chat_body = chat_body.split('\n    async function ', 1)[0]
        # Section regeneration is now handled by the model planner, not by a client-side
        # keyword shortcut inside sendTenantDesignerChat. The function still exists and is
        # reachable from the section-generate buttons; the chat sends every message to the
        # server and lets the model decide the action.
        self.assertIn("await requestTenantDesignerChat(chatPayload, indicator)", chat_body)
        self.assertIn("'/api/designer-chat/jobs'", index_source)

    def test_an_emptied_draft_can_be_refilled_from_a_presentation_snapshot(self):
        """Every generated presentation stored the whole project data of its moment, so a draft
        that was emptied by a bad save is recoverable from it."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        full = {
            'draftId': 'draft-recover', 'project_name': 'برج المشرق', 'city': 'الرياض',
            'croquis_land_area': '7012', 'allowed_uses': 'سكني وتجاري',
        }
        self.assertEqual(client.post('/api/project-draft', headers=headers,
                                     json={'draftData': full}).status_code, 200)
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض برج المشرق', 'projectData': full,
            'slidesData': [{'html': '<div class="slide">1</div>'}], 'slideCount': 1,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']

        # Simulate the historic wipe directly in the database, past the new guard.
        with self.app.app_context():
            conn = db.get_db()
            conn.execute("UPDATE project_drafts SET draft_data = '{}', title = 'مسودة مشروع بدون عنوان' "
                         'WHERE id = ?', ('draft-recover',))
            conn.commit()

        report = client.get('/api/project-drafts/recovery', headers=headers).get_json()
        entry = next(item for item in report['drafts'] if item['draftId'] == 'draft-recover')
        self.assertTrue(entry['isEmpty'])
        self.assertEqual(entry['fieldCount'], 0)
        self.assertEqual(entry['snapshot']['presentationId'], presentation_id)
        self.assertTrue(entry['snapshot']['recoverable'])
        self.assertGreaterEqual(entry['snapshot']['fieldCount'], 4)

        restored = client.post('/api/project-draft/draft-recover/restore', headers=headers,
                               json={'presentationId': presentation_id})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertGreaterEqual(restored.get_json()['restoredCount'], 4)

        draft = client.get('/api/project-draft/draft-recover', headers=headers).get_json()['draft']
        self.assertEqual(draft['draft_data']['project_name'], 'برج المشرق')
        self.assertEqual(draft['draft_data']['croquis_land_area'], '7012')
        self.assertEqual(draft['title'], 'برج المشرق')

        # Restoring never overwrites what the draft still holds.
        client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'draft-recover', 'project_name': 'اسم محدّث', 'city': 'الرياض',
            'croquis_land_area': '7012', 'allowed_uses': 'سكني وتجاري',
        }})
        again = client.post('/api/project-draft/draft-recover/restore', headers=headers,
                            json={'presentationId': presentation_id})
        self.assertEqual(again.get_json()['restoredCount'], 0)
        kept = client.get('/api/project-draft/draft-recover', headers=headers).get_json()['draft']
        self.assertEqual(kept['draft_data']['project_name'], 'اسم محدّث')

        # A snapshot from another tenant is never reachable.
        cross = client.post('/api/project-draft/draft-recover/restore',
                            headers=self._headers(self.token_b),
                            json={'presentationId': presentation_id})
        self.assertEqual(cross.status_code, 404)

        index_source = read_frontend_text()
        self.assertIn('/api/project-drafts/recovery', index_source)
        self.assertIn('async function restoreProjectDraft(draftId, presentationId)', index_source)
        self.assertIn('حقل ممتلئ', index_source)

    def test_slide_rules_forbid_invented_content_and_drawn_2d_plans(self):
        """Every number has to come from the project, and plans are uploaded images only."""
        rules = self.application_module.build_design_rules(
            {'primary_color': '#0b1f33', 'company_name': 'Landloom'})
        self.assertIn('ممنوع اختراع أي معلومة', rules)
        self.assertIn('ممنوع منعًا باتًا رسم أو تركيب أي مخطط معماري', rules)
        self.assertIn('##PLAN_IMAGE_1##', rules)
        self.assertIn('مواصفات الرسومات البيانية المعتمدة (4 أنواع لـ 4 مواقع محددة فقط)', rules)
        self.assertIn('ممنوع نهائياً Pie أو Donut أو Scatter أو Histogram', rules)
        self.assertIn('بحد أقصى 10% من لون التمييز', rules)
        self.assertIn('الوزن لخدمة التسلسل البصري', rules)
        self.assertIn('عنصرين أو ثلاثة مستقلين', rules)
        self.assertIn('من صورة واحدة إلى ثلاث صور', rules)
        self.assertIn('ممنوع إضافة ترجمة أو وصف', rules)
        # The batch path had its own copy of the 4,000-character cut.
        engine_source = read_module_source('slide_engine.py')
        self.assertNotIn("project_json[:4000]", engine_source)
        self.assertEqual(engine_source.count('build_project_facts(project_data'), 3)
