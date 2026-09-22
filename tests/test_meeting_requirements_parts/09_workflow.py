class MeetingRequirementsTestsPart08(MeetingRequirementsTests):

    def test_market_study_fields_and_section_are_wired(self):
        index_source = read_frontend_text()
        self.assertIn("function addMarketStudySection(form, before)", index_source)
        self.assertIn("addMarketStudySection(form);", index_source)
        self.assertIn("id = 'section-market-study'", index_source)
        self.assertIn("data-key=\"market_study_data\"", index_source)
        self.assertIn("function runMarketCompetitorsJob(mode)", index_source)
        self.assertIn("function runMarketSummaryJob()", index_source)
        self.assertIn('id="marketStudyOneBlockSummary"', index_source)
        self.assertIn('function buildMarketStudyOneBlockSummary(state = {})', index_source)
        self.assertIn('<th>القيمة (ر.س)</th>', index_source)
        self.assertIn('source_urls', index_source)
        self.assertNotIn('<textarea data-field="source_urls"', index_source)
        self.assertIn('id="marketSourcesTabs"', index_source)
        self.assertIn('id="marketSourcesPanels"', index_source)
        self.assertIn('function selectMarketSourceTab(key)', index_source)
        self.assertIn('class="market-sources-table"', index_source)
        self.assertNotIn('<table id="marketSourcesTable">', index_source)
        self.assertIn("tr.querySelectorAll('[data-source-links] a[href]')", index_source)
        self.assertIn('function mergeMarketSourceRows(existing, incoming)', index_source)
        self.assertIn('const visibleRows = Array.isArray(rows) && rows.length ? rows : [{}];', index_source)
        self.assertIn('function inferCompetitorPriceType(row = {})', index_source)
        self.assertIn('min-width: 1450px;', index_source)
        self.assertIn('width: max-content;', index_source)
        self.assertIn('min-width: 2300px;', index_source)
        self.assertIn('<textarea data-field="name" rows="2">', index_source)
        self.assertIn('<textarea data-field="note" rows="2">', index_source)
        self.assertIn("tr.querySelectorAll('input,select,textarea')", index_source)
        self.assertIn('<select data-field="classification">', index_source)
        self.assertIn('<td data-field="logo_cell"></td>', index_source)
        self.assertIn('data-currency="SAR"', index_source)
        self.assertIn('placeholder="من (ر.س)"', index_source)
        self.assertIn('#section-market-study th {', index_source)
        self.assertIn('color: var(--ink);', index_source)
        self.assertIn("function renderMarketSummaryCompare(current, incoming, currentSwot, incomingSwot)", index_source)
        self.assertIn('/api/market-study/competitors', index_source)
        self.assertIn('/api/market-study/summary', index_source)
        self.assertIn('/api/market-study/jobs/', index_source)
        self.assertIn('function enhanceProjectClassificationFields()', index_source)
        self.assertIn("id = 'projectAudienceGrid'", index_source)
        self.assertIn('id="marketCityMirror"', index_source)
        self.assertIn('const MARKET_GENERAL_AUDIENCE', index_source)
        self.assertIn('if (audienceWrap) audienceWrap.style.display = \'none\';', index_source)
        self.assertIn('function audienceOptionsForMain(main, subtype)', index_source)
        self.assertIn("const MARKET_GENERAL_AUDIENCE = ['أفراد', 'عائلات', 'مستثمرون', 'شركات', 'جهات حكومية', 'سياح وزوار', 'مشغلون ومستأجرون'];", index_source)
        self.assertIn('const MARKET_STUDY_SWOT_SECTIONS', index_source)
        self.assertIn("id=\"marketSwotFields\"", index_source)
        self.assertIn('تحليل SWOT', index_source)
        self.assertNotIn('const MARKET_OTHER_TYPE_OPTIONS', index_source)
        self.assertNotIn("id = 'projectOtherTypesGrid'", index_source)
        self.assertIn("id = 'projectTypeGrid'", index_source)
        self.assertIn("keepProjectMultiSelectOpen('projectTypeGrid')", index_source)
        self.assertIn('function persistProjectTypes(values)', index_source)
        self.assertIn("id = 'projectSubtypeGrid'", index_source)
        self.assertIn("id = 'projectActivityClassFields'", index_source)
        self.assertIn('function renderMultiSelectDropdown(host, options, selected, placeholder, onChange, closeAfterSelection = false)', index_source)
        self.assertIn('function keepProjectMultiSelectOpen(hostId)', index_source)
        self.assertIn('function closeOtherProjectMultiSelects(current)', index_source)
        self.assertIn('function refreshClassificationDependents()', index_source)
        self.assertNotIn("keepProjectMultiSelectOpen('projectSubtypeGrid')", index_source)
        self.assertIn('class="project-multi-select-option', index_source)
        self.assertIn("host.querySelectorAll('.project-multi-select-option')", index_source)
        self.assertNotIn('function reopenProjectMultiSelect', index_source)
        self.assertIn('function normalizeProjectTypeValue(raw)', index_source)
        self.assertIn('function applyProjectTypeSelect(input, raw)', index_source)
        self.assertIn('function selectedProjectTypeMains()', index_source)
        self.assertIn('function selectedProjectSubtypesByMain()', index_source)
        self.assertIn('function renderGroupedAudienceFields(mains, hidden, host)', index_source)
        self.assertIn('function audienceGroupInfo(main, subtype)', index_source)
        self.assertIn('function audienceValuesForGroup(current, group)', index_source)
        self.assertIn("groups.find(item => item.kind === info.kind)", index_source)
        self.assertIn('const MARKET_PROJECT_LEVELS', index_source)
        self.assertIn('function classificationGroupsForProject(mains, isOther, kinds)', index_source)
        self.assertNotIn('      kinds.forEach(addGroup);', index_source)
        self.assertIn("if (f.fieldKey === 'project_type') {", index_source)
        self.assertNotIn('otherHost.hidden = !isOther;', index_source)
        self.assertNotIn('🎯', index_source)

        app_source = read_module_source('app.py')
        self.assertIn("import market_study", app_source)
        self.assertIn("@app.route('/api/market-study/competitors'", app_source)
        self.assertIn("'type': 'openrouter:web_search',", app_source)
        self.assertIn('def _start_market_job(kind, executor):', app_source)

        self.assertIn('project_idea', {field['key'] for field in db.PREBUILT_FIELDS})
        self.assertNotIn('project_idea', db.REMOVED_PREBUILT_FIELDS)

    def test_market_study_merge_keeps_client_rows(self):
        import market_study
        existing = [{
            'id': 'keep-me',
            'name': 'مشروع العميل',
            'project_type': 'سكني',
            'status': 'قائم',
            'source': 'العميل',
            'row_source': 'manual',
        }]
        generated = [
            {'name': 'مشروع العميل', 'price_value': '1200000', 'source': 'منصة عقار'},
            {'name': 'منافس جديد', 'classification': 'مباشر', 'status': 'تحت الإنشاء'},
        ]
        merged, added, updated = market_study.merge_generated_competitors(existing, generated, mode='generate')
        self.assertEqual(added, 2)
        self.assertEqual(updated, 0)
        self.assertEqual([row['name'] for row in merged], ['مشروع العميل', 'منافس جديد'])
        self.assertEqual(merged[0]['source'], 'منصة عقار')
        self.assertEqual(len(merged), 2)

        filled, added_fill, updated_fill = market_study.merge_generated_competitors(
            existing, [
                {'name': 'مشروع العميل', 'price_value': '1200000', 'source': 'منصة عقار'},
                {'name': 'اسم غير موجود', 'status': 'قائم'},
            ], mode='fill'
        )
        self.assertEqual(added_fill, 0)
        self.assertEqual(updated_fill, 2)
        self.assertEqual([row['name'] for row in filled], ['مشروع العميل'])
        self.assertEqual(filled[0]['id'], 'keep-me')
        self.assertEqual(filled[0]['source'], 'العميل')
        self.assertEqual(filled[0]['price_type'], 'أخرى')
        self.assertEqual(filled[0]['price_value'], '1200000')

    def test_market_study_prefers_exact_page_urls_over_homepages(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'برج تجاري',
            'source': 'منصة عقار',
            'source_url': 'https://sa.aqar.fm/',
            'url': 'https://sa.aqar.fm/apartment-for-sale/12345',
        })
        self.assertEqual(row['source_url'], 'https://sa.aqar.fm/apartment-for-sale/12345')
        summary = market_study.normalize_summary({
            'decision': 'البيانات غير كافية',
            'sources': [{
                'name': 'الهيئة العامة للإحصاء',
                'url': 'https://www.stats.gov.sa/',
                'source_url': 'https://www.stats.gov.sa/statistics/housing-2024',
            }],
        })
        self.assertEqual(summary['sources'][0]['url'], 'https://www.stats.gov.sa/statistics/housing-2024')
        normalized = market_study.normalize_summary({
            'one_block_summary': 'عنوان الملخص\\n\\nفقرة الملخص.',
            'summary': {},
        })
        self.assertEqual(normalized['one_block_summary'], 'عنوان الملخص فقرة الملخص.')
        summary_prompt = market_study.build_summary_user_prompt({}, [])
        self.assertIn('one_block_summary', summary_prompt)
        prompt = market_study.build_consultant_system_prompt()
        self.assertIn('رابط الصفحة بالضبط', prompt)

    def test_market_study_keeps_all_competitor_urls_and_builds_source_rows(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'برج الأعمال',
            'operation_type': 'بيع',
            'price_type': 'سعر المتر المربع',
            'price_value': '4500',
            'source_urls': [
                'https://developer.example/project',
                'https://listing.example/project-123',
            ],
            'field_sources': {
                'name': ['https://developer.example/project'],
                'area_sqm': ['https://listing.example/project-123'],
            },
            'source': 'المطور ومنصة الإعلانات',
        })
        self.assertEqual(row['source_url'], 'https://developer.example/project')
        self.assertEqual(row['source_urls'], [
            'https://developer.example/project',
            'https://listing.example/project-123',
        ])
        self.assertEqual(row['field_sources'], {
            'name': ['https://developer.example/project'],
            'area_sqm': ['https://listing.example/project-123'],
        })
        self.assertEqual(row['price_type'], 'سعر المتر المربع')
        self.assertEqual(row['price_value'], '4500')
        sources = market_study.competitor_source_rows([row])
        self.assertEqual([item['url'] for item in sources], row['source_urls'])
        self.assertEqual([item['competitor_name'] for item in sources], ['برج الأعمال', 'برج الأعمال'])
        self.assertEqual(sources[0]['source_fields'], ['اسم المشروع'])
        self.assertEqual(sources[1]['source_fields'], ['مساحة الوحدة'])

    def test_market_study_normalizes_price_object_and_operation_aliases(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'فندق الأعمال',
            'project_type': 'فندقي',
            'operation': 'sale',
            'price': {'type': 'سعر الوحدة', 'value': 1200000},
            'sources': [
                {'url': 'https://developer.example/hotel'},
                {'source_url': 'https://listing.example/hotel-1'},
            ],
        })
        self.assertEqual(row['operation_type'], 'بيع')
        self.assertEqual(row['price_type'], 'سعر الوحدة')
        self.assertEqual(row['price_value'], '1200000')
        self.assertEqual(row['source_urls'], [
            'https://developer.example/hotel',
            'https://listing.example/hotel-1',
        ])
        derived = market_study.normalize_competitor_row({
            'name': 'وحدة سكنية',
            'price_type': 'سعر الوحدة',
            'price_value': '900000',
        })
        self.assertEqual(derived['operation_type'], 'بيع')

    def test_market_study_accepts_arabic_price_aliases(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'فندق جدة',
            'project_type': 'فندقي',
            'operation': 'تشغيل',
            'نوع السعر': 'سعر الليلة',
            'القيمة': '1548',
            'field_sources': {
                'price_type': ['https://example.com/price'],
                'price_value': ['https://example.com/price'],
            },
        })
        self.assertEqual(row['operation_type'], 'تشغيل فندقي')
        self.assertEqual(row['price_type'], 'سعر الليلة')
        self.assertEqual(row['price_value'], '1548')
        ranged = market_study.normalize_competitor_row({
            'name': 'فندق جدة بنطاق سعري',
            'operation': 'تشغيل',
            'نوع السعر': 'نطاق أسعار الغرف',
            'من': '900',
            'إلى': '1500',
        })
        self.assertEqual(ranged['price_type'], 'نطاق أسعار الغرف')
        self.assertEqual(ranged['price_from'], '900')
        self.assertEqual(ranged['price_to'], '1500')

    def test_market_study_supports_fixed_and_range_areas_and_permanent_source_deletion(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'id': 'c1', 'name': 'مشروع النخيل', 'area_mode': 'range',
            'area_from': '١،٢٠٠.55', 'area_to': '2,500',
            'price_value': '1,500,000', 'source': 'الموقع الرسمي للمشروع',
            'source_urls': ['https://nakheel.example/project'],
            'field_sources': {'price_value': ['https://nakheel.example/project']},
        })
        self.assertEqual(row['area_mode'], 'range')
        self.assertEqual(row['area_sqm'], '')
        self.assertEqual(row['area_from'], '1200.6')
        self.assertEqual(row['area_to'], '2500')
        self.assertEqual(row['price_value'], '1500000')
        sources = market_study.competitor_source_rows([row])
        self.assertEqual(sources[0]['reliability'], 'مصدر رسمي للجهة')
        cleaned = market_study.remove_url_from_competitor(row, 'https://nakheel.example/project')
        self.assertEqual(cleaned['name'], 'مشروع النخيل')
        self.assertEqual(cleaned['price_value'], '1500000')
        self.assertEqual(cleaned['source_urls'], [])
        self.assertEqual(cleaned['field_sources'], {})
        index_source = read_frontend_text()
        area_source = index_source[index_source.index('function renderCompetitorAreaInputs'):
                                   index_source.index('function competitorLogoPath')]
        for expected in ('data-field="area_mode"', 'data-field="area_sqm"', 'data-field="area_from"',
                         'data-field="area_to"', 'نطاق من — إلى'):
            self.assertIn(expected, area_source)
        for expected in ('removeMarketSourcePermanently', 'formatMarketNumericInput', 'cacheCompetitorAreaInputs'):
            self.assertIn(expected, index_source)
        formatted = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide"><table><tr><td>2027</td><td>1500000</td></tr></table></div>',
            'content', {}, {'primary_color': '#123456'}, content_source='financial_report:1:0:1')
        self.assertIn('1,500,000', formatted)
        self.assertIn('2027', formatted)
        self.assertNotIn('2,027', formatted)

    def test_market_fill_preserves_client_values_sources_logos_and_records_conflicts(self):
        import market_study
        official = 'https://developer.example/project/prices'
        existing = [{
            'id': 'client-row', 'name': 'مشروع العميل', 'project_type': 'سكني',
            'area_sqm': '120.25', 'status': '', 'classification': 'مباشر',
            'operation_type': 'بيع', 'price_type': 'سعر الوحدة', 'price_value': '1000000',
            'source': 'إدخال العميل', 'logo_file_id': 'manual-logo', 'logo_path': '/uploads/manual.png',
        }]
        generated = [{
            'id': 'client-row', 'name': 'مشروع العميل', 'project_type': 'تجاري',
            'area_sqm': '150', 'status': 'قائم', 'classification': 'مرجعي',
            'operation_type': 'بيع', 'price_type': 'نطاق سعري',
            'price_from': '900000', 'price_to': '1300000',
            'source': 'الموقع الرسمي للمطور', 'source_url': official,
            'source_urls': [official],
            'logo_url': 'https://developer.example/logo.png', 'logo_source_url': official,
            'field_sources': {
                'project_type': [official], 'area_sqm': [official], 'status': [official],
                'classification': [official], 'price_type': [official],
                'price_from': [official], 'price_to': [official], 'logo_url': [official],
            },
        }]
        merged, added, updated = market_study.merge_generated_competitors(existing, generated, mode='fill')
        self.assertEqual(added, 0)
        self.assertGreaterEqual(updated, 1)
        row = merged[0]
        self.assertEqual(row['project_type'], 'سكني')
        self.assertEqual(row['area_sqm'], '120.3')
        self.assertEqual(row['classification'], 'مباشر')
        self.assertEqual(row['price_type'], 'سعر الوحدة')
        self.assertEqual(row['price_value'], '1000000')
        self.assertEqual(row['status'], 'قائم')
        self.assertEqual(row['field_sources']['status'], [official])
        self.assertEqual(row['logo_file_id'], 'manual-logo')
        self.assertEqual(row['logo_path'], '/uploads/manual.png')
        self.assertFalse(row['logo_url'])
        warning_fields = {warning['field'] for warning in row['conflict_warnings']}
        self.assertTrue({'project_type', 'area_mode', 'classification', 'price_type'} <= warning_fields)

        prompt = market_study.build_competitors_user_prompt({'city': 'جدة'}, existing, mode='fill')
        self.assertIn('"area_mode"', prompt)
        self.assertIn('"area_from"', prompt)
        self.assertIn('"area_to"', prompt)
        self.assertIn('املأ الحقول الناقصة فقط', prompt)
        index_source = read_frontend_text()
        self.assertIn('cacheCompetitorPriceInputs', index_source)
        self.assertIn('price_cache: competitorPriceCache(tr)', index_source)
        self.assertIn('data-field="classification"', index_source)

    def test_market_study_radius_auto_is_ten_km(self):
        import market_study
        self.assertNotIn('auto', [item['value'] for item in market_study.COMPETITOR_RADIUS_OPTIONS])
        self.assertEqual(market_study.resolve_competitor_radius_km(None), 10)
        self.assertEqual(market_study.resolve_competitor_radius_km('auto'), 10)
        self.assertEqual(market_study.resolve_competitor_radius_km('custom', 7), 7)
        self.assertIsNone(market_study.resolve_competitor_radius_km('city'))
        index_source = read_frontend_text()
        self.assertNotIn('تلقائي حسب نوع المشروع', index_source)
        self.assertIn('<option value="10" selected>10 كم</option>', index_source)

    def test_market_study_searches_before_it_falls_back_to_json_mode(self):
        module = self.application_module
        responses = [
            {'error': {'message': 'web search response was empty'}},
            {'choices': [{'message': {'content': 'not valid json'}}]},
            {'choices': [{'message': {'content': 'still not json'}}]},
            {'choices': [{'message': {'content': '{"competitors": []}'}}]},
        ]
        calls = []

        def fake_call(system_prompt, user_content, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call) as call:
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)

        self.assertTrue(module._has_chat_choices(response))
        self.assertEqual(call.call_count, 4)
        # Gemini answers a tools + JSON-mode call with reasoning only, so searching with
        # JSON mode off must be the first attempt or no search ever runs.
        self.assertIsNotNone(calls[0]['tools'])
        self.assertIsNone(calls[0]['response_format'])
        self.assertIsNotNone(calls[1]['tools'])
        self.assertEqual(calls[1]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[2]['tools'])
        self.assertEqual(calls[2]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[3]['tools'])
        self.assertIsNone(calls[3]['response_format'])
        self.assertEqual(error, '')

    def test_market_study_uses_the_retrieved_page_for_homepage_links(self):
        import market_study
        module = self.application_module
        citations = [
            'https://sa.aqar.fm/',
            'https://sa.aqar.fm/%D8%B4%D9%82%D9%82-%D9%84%D9%84%D8%A8%D9%8A%D8%B9/12345',
            'https://www.stats.gov.sa/statistics/housing-2026',
        ]
        response = {'choices': [{'message': {'annotations': [
            {'type': 'url_citation', 'url_citation': {'url': url}} for url in citations
        ]}}]}
        self.assertEqual(module._market_citation_urls(response), citations)
        rows = [
            {'name': 'برج سكني', 'source_url': 'https://sa.aqar.fm/', 'row_source': 'ai'},
            {'name': 'برج العميل', 'source_url': 'https://sa.aqar.fm/', 'row_source': 'user'},
        ]
        market_study.apply_search_citations(rows, citations)
        self.assertEqual(rows[0]['source_url'], citations[1])
        self.assertEqual(rows[1]['source_url'], 'https://sa.aqar.fm/')
        sources = [{'name': 'الهيئة العامة للإحصاء', 'url': 'https://www.stats.gov.sa'}]
        market_study.apply_search_citations(sources, citations, url_key='url')
        self.assertEqual(sources[0]['url'], citations[2])
        multi = [{
            'name': 'برج متعدد المصادر',
            'source_urls': ['https://sa.aqar.fm/', 'https://www.stats.gov.sa/statistics/housing-2026'],
            'row_source': 'ai',
        }]
        market_study.apply_search_citations(multi, citations)
        self.assertEqual(multi[0]['source_urls'], [citations[1], citations[2]])
        self.assertEqual(multi[0]['source_url'], citations[1])
        prompt = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        self.assertIn('رابط النطاق وحده أو الصفحة الرئيسية غير مقبول', prompt)
        app_source = read_module_source('app.py')
        self.assertIn("market_study.apply_search_citations(merged, citation_urls)", app_source)

    def test_portal_homepage_links_resolve_to_the_dataset_page(self):
        import market_study
        # rei.rega.gov.sa/ar is a navigation shell — sale figures live behind the
        # deals view and rental figures behind the detailed indicator. A row that
        # cites only the portal homepage must end up pointing at the dataset page.
        sale = {
            'name': 'برج بيعي',
            'operation_type': 'بيع',
            'source_url': 'https://rei.rega.gov.sa/ar',
            'source_urls': ['https://rei.rega.gov.sa/ar'],
            'field_sources': {'price_value': ['https://rei.rega.gov.sa/ar']},
            'row_source': 'ai',
        }
        rental = {
            'name': 'مجمع إيجاري',
            'operation_type': 'إيجار',
            'source_url': 'https://rei.rega.gov.sa/ar',
            'source_urls': ['https://rei.rega.gov.sa/ar', 'https://sakani.sa'],
            'field_sources': {'price_value': ['https://sakani.sa']},
            'row_source': 'ai',
        }
        market_study.apply_search_citations([sale, rental], [])
        self.assertEqual(sale['source_url'], 'https://rei.rega.gov.sa/ar/advanced-search/deals')
        self.assertEqual(sale['source_urls'], ['https://rei.rega.gov.sa/ar/advanced-search/deals'])
        self.assertEqual(
            sale['field_sources']['price_value'],
            ['https://rei.rega.gov.sa/ar/advanced-search/deals'])
        self.assertEqual(
            rental['field_sources']['price_value'], ['https://sakani.sa/reports-and-data'])
        self.assertIn(
            'https://rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator',
            rental['source_urls'])
        self.assertIn('https://sakani.sa/reports-and-data', rental['source_urls'])
        self.assertTrue(all(
            not market_study.is_generic_source_homepage(url) for url in rental['source_urls']))
        # A retrieved page on the same host still wins over the canonical map.
        retrieved = ['https://rei.rega.gov.sa/ar/advanced-search/deals?deal=1']
        cited = {
            'name': 'برج', 'operation_type': 'بيع',
            'source_url': 'https://rei.rega.gov.sa/ar', 'row_source': 'ai',
        }
        market_study.apply_search_citations([cited], retrieved)
        self.assertEqual(cited['source_url'], retrieved[0])
        # Non-portal homepages stay untouched.
        other = {
            'name': 'برج', 'operation_type': 'بيع',
            'source_url': 'https://developer.sa/', 'row_source': 'ai',
        }
        market_study.apply_search_citations([other], [])
        self.assertEqual(other['source_url'], 'https://developer.sa/')
        # Links merged in by the per-competitor verification get normalized too.
        merged = {
            'name': 'برج', 'operation_type': 'بيع',
            'source_url': 'https://rei.rega.gov.sa',
            'source_urls': ['https://rei.rega.gov.sa', 'https://dev.sa/proj/1'],
        }
        market_study.canonicalize_competitor_source_urls(merged)
        self.assertEqual(
            merged['source_urls'][0], 'https://rei.rega.gov.sa/ar/advanced-search/deals')
        self.assertEqual(
            merged['source_url'], 'https://rei.rega.gov.sa/ar/advanced-search/deals')

    def test_competitor_verification_captures_retrieved_price(self):
        module = self.application_module
        price_page = 'https://sa.aqar.fm/listing/9'
        official_page = 'https://developer.sa/olu-alrehab'
        response = {
            'choices': [{'message': {
                'content': json.dumps({'exists': True, 'price': {
                    'type': 'إيجار الوحدة السنوي', 'value': '45000', 'url': price_page}}),
                'annotations': [
                    {'type': 'url_citation', 'url_citation': {
                        'url': price_page, 'title': 'مشروع علو الرحاب شقق للإيجار'}},
                    {'type': 'url_citation', 'url_citation': {
                        'url': official_page,
                        'title': 'مشروع علو الرحاب — الموقع الرسمي'}},
                ],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        row = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار', 'row_source': 'ai'}
        with patch.object(module, '_call_market_study_model', return_value=(response, '')):
            module._verify_competitor_row(row, {'city': 'جدة'}, {})
        self.assertEqual(row.get('price_value'), '45000')
        self.assertEqual(row.get('price_type'), 'إيجار الوحدة السنوي')
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn(price_page, row.get('field_sources', {}).get('price_value', []))
        self.assertIn(price_page, row.get('source_urls') or [])
        # A price citing a page the search never retrieved is rejected — the
        # figure could be memory dressed up as evidence.
        ghost = {
            'choices': [{'message': {
                'content': json.dumps({'exists': True, 'price': {
                    'type': 'إيجار الوحدة السنوي', 'value': '45000',
                    'url': 'https://never-retrieved.example/page'}}),
                'annotations': [
                    {'type': 'url_citation', 'url_citation': {
                        'url': official_page,
                        'title': 'مشروع علو الرحاب — الموقع الرسمي'}},
                ],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        rejected = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار', 'row_source': 'ai'}
        with patch.object(module, '_call_market_study_model', return_value=(ghost, '')):
            module._verify_competitor_row(rejected, {'city': 'جدة'}, {})
        self.assertFalse(rejected.get('price_value'))
        # An evidence-backed price from the main pass is never overwritten.
        filled = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار',
                  'price_value': '30000', 'row_source': 'ai'}
        with patch.object(module, '_call_market_study_model', return_value=(response, '')):
            module._verify_competitor_row(filled, {'city': 'جدة'}, {})
        self.assertEqual(filled.get('price_value'), '30000')
        # Same-name projects in other Arab markets are not evidence: a Dubai
        # page must not feed the row, its price, or its logo.
        foreign_res = {
            'choices': [{'message': {
                'content': json.dumps({'exists': True, 'price': {
                    'type': 'إيجار الوحدة السنوي', 'value': '45000',
                    'url': 'https://propertyfinder.ae/ar/new-projects/olu'}}),
                'annotations': [
                    {'type': 'url_citation', 'url_citation': {
                        'url': 'https://propertyfinder.ae/ar/new-projects/olu',
                        'title': 'مشروع علو الرحاب دبي'}},
                ],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        foreign = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار', 'row_source': 'ai'}
        with patch.object(module, '_call_market_study_model', return_value=(foreign_res, '')):
            module._verify_competitor_row(foreign, {'city': 'جدة'}, {})
        self.assertTrue(foreign.get('no_search_evidence'))
        self.assertEqual(foreign.get('verify_state'), 'no_match')
        self.assertFalse(foreign.get('price_value'))
        self.assertFalse(foreign.get('logo_source_url'))
        # A generic .com portal whose path names another Arab market is still
        # foreign: the live run attached a dubai-silicon-oasis namesake page to
        # a Saudi «أورا» row because only the host was inspected.
        self.assertTrue(module._foreign_market_host(
            'https://aigentsrealty.com/ar/areas/dubai-silicon-oasis/aura-prestige'))
        self.assertFalse(module._foreign_market_host(
            'https://nhc.sa/real-estate-development/projects/304/'))
        row = {'name': 'مشروع أورا', 'row_source': 'ai',
               'source_urls': [
                   'https://aigentsrealty.com/ar/areas/dubai-silicon-oasis/aura-prestige',
                   'https://sabq.org/article/4sxj0z4']}
        module._drop_foreign_competitor_urls(row)
        self.assertEqual(row.get('source_urls'), ['https://sabq.org/article/4sxj0z4'])
        # A provider that returns no citations is an infrastructure miss, not a
        # fabricated name — it must not be mislabeled as unverified.
        silent = {'choices': [{'message': {'content': '{"exists": true}'}}]}
        quiet = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار', 'row_source': 'ai'}
        with patch.object(module, '_call_market_study_model', return_value=(silent, '')):
            module._verify_competitor_row(quiet, {'city': 'جدة'}, {})
        self.assertEqual(quiet.get('verify_state'), 'search_not_run')
        self.assertFalse(quiet.get('no_search_evidence'))

    def test_market_study_prices_require_a_dedicated_search(self):
        import market_study
        prompt = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        # One market-wide search cannot price six competitors; every price used to come back
        # empty because the model searched once and answered the rest from memory.
        self.assertIn('بروتوكول البحث الإلزامي', prompt)
        self.assertIn('نفّذ بحثًا منفصلًا لكل منافس على حدة عن سعره الفعلي', prompt)
        self.assertIn('لا تكتب سعرًا من معرفتك السابقة', prompt)
        self.assertIn('source_urls', prompt)
        self.assertIn('field_sources', prompt)
        self.assertIn('مساحة الوحدة القابلة للبيع', prompt)
        self.assertIn('Tower GFA', prompt)
        self.assertIn('price_type والقيمة', prompt)
        self.assertIn(market_study.MISSING_VALUE_PHRASE, prompt)
        self.assertIn('سعر الليلة', prompt)
        self.assertIn('متوسط سعر الغرفة ADR', prompt)
        self.assertIn('إيجار المتر السنوي', prompt)
        app_source = read_module_source('app.py')
        self.assertIn("'max_uses': 10", app_source)
        self.assertIn("MARKET_SEARCH_ENGINE", app_source)
        # The `web` plugin grounds every market call once — the server tool
        # alone left the search decision to the model, which could skip it.
        self.assertIn("'id': 'web'", app_source)
        self.assertIn("plugins=plugins", app_source)

    def test_market_study_prompt_carries_financial_and_site_context(self):
        import market_study
        payload = {
            'city': 'جدة',
            'financial': {
                'unitRevenueMode': 'rental',
                'projectCost': 800_000_000,
                'noiY1': 45_000_000,
                'projectIrr': 0.183,
                'payback': 6.5,
                'developmentYears': 4,
                'salesStartYear': 1,
                'operationYears': 10,
                'floorCount': 20,
                'coverageRate': 0.6,
            },
            'approvedFloorCount': '20',
            'approvedCoverageRatio': '60%',
            'mainRoads': 'طريق الملك فهد\nطريق التحلية',
            'nearbyLandmarks': ['مجمع الراشد (تسوق)', 'مستشفى الحرس'],
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'annualRent'},
            ],
        }
        prompt = market_study.build_competitors_user_prompt(payload, [], mode='generate')
        self.assertIn('وحدات تأجيرية فقط', prompt)
        self.assertIn('مؤشرات الدراسة المالية', prompt)
        self.assertIn('800.0 مليون ريال', prompt)
        self.assertIn('45.0 مليون ريال', prompt)
        self.assertIn('18.3%', prompt)
        self.assertIn('طريق الملك فهد', prompt)
        self.assertIn('مجمع الراشد (تسوق)', prompt)
        self.assertIn('annualRent = إيجار سنوي', prompt)
        self.assertIn('طبيعة الإيرادات في بيانات المشروع ملزمة', prompt)
        # A project with no financial data must not render the block at all.
        bare = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        self.assertNotIn('مؤشرات الدراسة المالية', bare)

    def test_market_study_lowers_token_cap_when_credit_is_limited(self):
        module = self.application_module
        refusal = {'error': {'message': 'You requested up to 6000 tokens, but can only afford 3000'}}
        success = {
            'choices': [{'message': {'content': '{"competitors": []}'}}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        caps = []

        def fake_call(system_prompt, user_content, **kwargs):
            caps.append(kwargs['max_tokens'])
            return refusal if len(caps) == 1 else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call):
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)

        self.assertTrue(module._has_chat_choices(response))
        self.assertEqual(error, '')
        self.assertEqual(caps, [6000, 2550])

    def test_market_study_endpoints_queue_or_run_without_deleting_rows(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        fake = {
            'competitors': [
                {
                    'name': 'برج الشمال',
                    'project_type': 'سكني',
                    'classification': 'مباشر',
                    'status': 'قائم',
                    'operation_type': 'بيع',
                    'price_type': 'سعر الوحدة',
                    'price_value': '1200000',
                    'source': 'موقع المطور',
                    'source_urls': [
                        'https://developer.example/north-tower',
                        'https://listing.example/north-tower',
                    ],
                }
            ]
        }
        fake_response = {
            'choices': [{'message': {'content': json.dumps(fake, ensure_ascii=False)}}],
            'usage': {'server_tool_use': {'web_search_requests': 3}},
        }
        with patch.object(self.application_module, '_call_market_study_model', return_value=(
            fake_response,
            '',
        )), patch.object(self.application_module, '_verify_market_urls', return_value=set()):
            generated = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني',
                'city': 'الرياض',
                'mode': 'generate',
                'competitors': [{'id': 'c1', 'name': 'منافس العميل', 'row_source': 'manual'}],
            })
            filled = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني',
                'city': 'الرياض',
                'mode': 'fill',
                'competitors': [{'id': 'c1', 'name': 'منافس العميل', 'row_source': 'manual'}],
            })
        self.assertEqual(generated.status_code, 200, generated.get_json())
        generated_payload = generated.get_json()
        generated_names = [row['name'] for row in generated_payload['competitors']]
        self.assertEqual(generated_names, ['برج الشمال'])
        self.assertEqual(
            [row['url'] for row in generated_payload['sources']],
            ['https://developer.example/north-tower', 'https://listing.example/north-tower'],
        )
        self.assertEqual(filled.status_code, 200, filled.get_json())
        filled_names = [row['name'] for row in filled.get_json()['competitors']]
        self.assertEqual(filled_names, ['منافس العميل'])

        catalog = client.get('/api/market-study/catalog', headers=headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertIn('سكني', catalog.get_json()['catalog']['projectTypes'])
        self.assertEqual(
            [item['key'] for item in catalog.get_json()['catalog']['swotSections']],
            ['strengths', 'weaknesses', 'opportunities', 'threats']
        )

        missing = client.get('/api/market-study/jobs/not-a-job-id-xxx', headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_market_competitors_strip_sources_when_no_search_ran(self):
        """A parseable answer with zero executed searches is memory, not evidence."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        fake = {
            'competitors': [{
                'name': 'برج الوهم',
                'project_type': 'سكني',
                'source': 'موقع المطور',
                'source_url': 'https://developer.example/tower',
                'source_urls': ['https://developer.example/tower'],
                'logo_url': 'https://developer.example/logo.png',
                'logo_source_url': 'https://developer.example',
            }]
        }
        memory_response = {
            'choices': [{'message': {'content': json.dumps(fake, ensure_ascii=False)}}],
        }
        with patch.object(self.application_module, '_call_market_study_model', return_value=(
            memory_response, '',
        )):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        self.assertEqual(res.status_code, 200, res.get_json())
        payload = res.get_json()
        self.assertFalse(payload.get('searchVerified'))
        row = payload['competitors'][0]
        self.assertTrue(row.get('sources_unverified'))
        # Unverified links stay visible for the owner to review — flagged,
        # never deleted.
        self.assertEqual(row.get('source_urls'), ['https://developer.example/tower'])
        self.assertEqual(row.get('source_url'), 'https://developer.example/tower')
        self.assertEqual(row.get('logo_url'), 'https://developer.example/logo.png')
        self.assertFalse(row.get('dead_source_urls'))
        source_rows = payload.get('sources') or []
        self.assertEqual([s['url'] for s in source_rows], ['https://developer.example/tower'])
        self.assertIn('رابط غير موثق', source_rows[0].get('note') or '')

    def test_market_competitors_prune_dead_urls(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        fake = {
            'competitors': [{
                'name': 'برج الجنوب',
                'project_type': 'سكني',
                'source': 'موقع المطور',
                'source_urls': [
                    'https://developer.example/south-tower',
                    'https://dead.example/gone',
                ],
            }]
        }
        verified_response = {
            'choices': [{'message': {'content': json.dumps(fake, ensure_ascii=False)}}],
            'usage': {'server_tool_use': {'web_search_requests': 2}},
        }
        with patch.object(self.application_module, '_call_market_study_model', return_value=(
            verified_response, '',
        )), patch.object(self.application_module, '_verify_market_urls',
                         return_value={'https://dead.example/gone'}):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        self.assertEqual(res.status_code, 200, res.get_json())
        row = res.get_json()['competitors'][0]
        # Dead links stay on the row for review — flagged, not deleted.
        self.assertEqual(row.get('source_urls'), [
            'https://developer.example/south-tower', 'https://dead.example/gone'])
        self.assertIn('https://dead.example/gone', row.get('dead_source_urls') or [])
        sources = res.get_json()['sources']
        dead_source = next(s for s in sources if s['url'] == 'https://dead.example/gone')
        self.assertIn('لم يعد يعمل', dead_source.get('note') or '')

    def test_market_competitors_flag_out_of_radius_rows(self):
        import market_study
        rows = [
            {'name': 'داخل النطاق', 'row_source': 'ai', 'distance_km': '4'},
            {'name': 'خارج النطاق', 'row_source': 'ai', 'distance_km': '15'},
            {'name': 'يدوي خارج النطاق', 'row_source': 'manual', 'distance_km': '30'},
        ]
        flagged = market_study.flag_out_of_radius(rows, 5)
        self.assertEqual(flagged, 1)
        self.assertTrue(rows[1].get('out_of_radius'))
        self.assertFalse(rows[0].get('out_of_radius'))
        self.assertFalse(rows[2].get('out_of_radius'))
        self.assertTrue(rows[1]['conflict_warnings'])

    def test_market_sources_flag_out_of_period(self):
        import market_study
        bounds = {'from': '2025-09-01', 'to': '2026-09-01'}
        sources = [
            {'name': 'أ', 'url': 'https://a.example/x', 'data_date': '2026-01'},
            {'name': 'ب', 'url': 'https://b.example/y', 'data_date': '2022'},
            {'name': 'ج', 'url': 'https://c.example/z', 'data_date': ''},
        ]
        flagged = market_study.flag_out_of_period_sources(sources, bounds)
        self.assertEqual(flagged, 1)
        self.assertTrue(sources[1].get('outside_data_period'))
        self.assertIn('خارج فترة البيانات المحددة', sources[1].get('note') or '')
        self.assertFalse(sources[0].get('outside_data_period'))
        self.assertFalse(sources[2].get('outside_data_period'))

    def test_market_study_model_retries_when_search_never_ran(self):
        module = self.application_module
        memory = {'choices': [{'message': {'content': '{"competitors": []}'}}]}
        searched = {
            'choices': [{'message': {'content': '{"competitors": []}'}}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        calls = []

        def fake_call(system_prompt, user_content, **kwargs):
            calls.append(kwargs.get('tools'))
            return memory if len(calls) == 1 else searched

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call):
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)
        self.assertEqual(error, '')
        self.assertIs(response, searched)
        self.assertTrue(all(calls), 'tool attempts must keep the search tool')
        self.assertEqual(len(calls), 2)

    def test_market_study_model_accepts_memory_answer_as_last_resort(self):
        module = self.application_module
        memory = {'choices': [{'message': {'content': '{"competitors": []}'}}]}

        with patch.object(module, 'call_openrouter_chat', return_value=memory):
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)
        self.assertEqual(error, '')
        self.assertIs(response, memory)

    def test_market_study_model_rejects_malformed_function_call(self):
        """JSON parseable out of reasoning is not an answer when the provider
        aborted — it used to be accepted and surfaced as a silent success."""
        module = self.application_module
        malformed = {
            'choices': [{
                'native_finish_reason': 'MALFORMED_FUNCTION_CALL',
                'message': {
                    'content': '',
                    'reasoning': '{"competitors": [{"name": "برج الوهم"}]}',
                    'annotations': [{'url_citation': {
                        'url': 'https://developer.example/x', 'title': 'صفحة'}}],
                },
            }],
        }
        with patch.object(module, 'call_openrouter_chat', return_value=malformed) as fake_call:
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)
        self.assertTrue(error)
        self.assertIn('MALFORMED_FUNCTION_CALL', error)
        self.assertFalse(response.get('choices'))
        self.assertGreaterEqual(fake_call.call_count, 2)

    def test_attach_retrieved_citations_adds_match_beside_generic_portal(self):
        """A row already carrying the generic REI link still gains the retrieved
        page that actually names the competitor."""
        module = self.application_module
        row = {
            'name': 'مشروع النخبة', 'row_source': 'ai',
            'source_url': 'https://rei.rega.gov.sa/ar',
            'source_urls': ['https://rei.rega.gov.sa/ar'],
        }
        pages = [
            {'url': 'https://rei.rega.gov.sa/ar', 'title': 'المؤشرات العقارية', 'content': ''},
            {'url': 'https://developer.example/al-nukhbah',
             'title': 'مشروع النخبة — الموقع الرسمي', 'content': ''},
        ]
        module._attach_retrieved_citations([row], pages)
        self.assertIn('https://developer.example/al-nukhbah', row['source_urls'])
        self.assertIn('https://rei.rega.gov.sa/ar', row['source_urls'])
        self.assertEqual(row['source_url'], 'https://developer.example/al-nukhbah')

    def test_verify_competitor_matches_name_in_citation_content(self):
        """A retrieved page whose excerpt names the competitor counts even when
        its title and URL are generic."""
        module = self.application_module
        row = {'name': 'مجمع الفرسان', 'row_source': 'ai', 'id': 'r1'}
        response = {
            'choices': [{'message': {
                'content': '{"exists": true, "price": {"value": "450000", '
                           '"url": "https://developer.example/listing-77"}}',
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/listing-77',
                    'title': 'عقارات للبيع',
                    'content': 'مجمع الفرسان السكني — أسعار تبدأ من 450000'}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        with patch.object(module, '_call_market_study_model', return_value=(response, '')):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn('https://developer.example/listing-77', row.get('source_urls') or [])
        self.assertIn('450000', str(row.get('price_value') or ''))

    def test_verify_competitor_keeps_searching_until_price_found(self):
        """Proving the name is not the finish line — while the price stays
        empty the next query angle still runs."""
        module = self.application_module
        row = {'name': 'مجمع الفرسان', 'row_source': 'ai', 'id': 'r1'}
        identity = {
            'choices': [{'message': {
                'content': '{"exists": true, "price": {}}',
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/fursan',
                    'title': 'مجمع الفرسان', 'content': ''}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        priced = {
            'choices': [{'message': {
                'content': '{"exists": true, "price": {"value": "320000", '
                           '"url": "https://developer.example/fursan-prices"}}',
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/fursan-prices',
                    'title': 'أسعار مجمع الفرسان', 'content': ''}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        calls = []

        def fake_model(*_args, **_kwargs):
            calls.append(1)
            return (identity, '') if len(calls) == 1 else (priced, '')

        with patch.object(module, '_call_market_study_model', side_effect=fake_model):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn('320000', str(row.get('price_value') or ''))
        self.assertGreaterEqual(len(calls), 2)

    def test_verify_competitor_rows_includes_manual_rows(self):
        """Fill mode completes cells the user left empty — manual rows get the
        same per-name search; their values are never overwritten."""
        module = self.application_module
        rows = [
            {'name': 'مجمع العميل اليدوي', 'row_source': 'manual',
             'price_value': '900000'},
            {'name': 'منافس مولد', 'row_source': 'ai'},
        ]
        searched = {
            'choices': [{'message': {'content': '{"exists": true}', 'annotations': []}}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        prompts = []

        def fake_model(*args, **_kwargs):
            prompts.append(args[1] if len(args) > 1 else '')
            return searched, ''

        with patch.object(module, '_call_market_study_model', side_effect=fake_model):
            module._verify_competitor_rows(rows, {'city': 'الرياض'}, {})
        self.assertTrue(any('اليدوي' in str(prompt) for prompt in prompts),
                        'manual row never received a verification search')
        self.assertTrue(any('مولد' in str(prompt) for prompt in prompts))
        self.assertEqual(rows[0].get('price_value'), '900000')

    def test_market_competitors_single_generic_citation_is_partial(self):
        """Six competitors sharing one portal citation is a partial result, not
        a clean success — the response must say so."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        names = ['مجمع الفرسان', 'واحة الريان', 'برج السدرة', 'مشروع النخبة',
                 'مجمع الياسمين', 'برج الوفرة']
        fake = {'competitors': [
            {'name': name, 'project_type': 'سكني',
             'source_url': 'https://rei.rega.gov.sa/ar',
             'source_urls': ['https://rei.rega.gov.sa/ar']}
            for name in names
        ]}
        grounded = {
            'choices': [{'message': {
                'content': json.dumps(fake, ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://rei.rega.gov.sa/ar', 'title': 'المؤشرات العقارية'}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 3}},
        }
        with patch.object(self.application_module, '_call_market_study_model',
                          return_value=(grounded, '')), \
                patch.object(self.application_module, '_verify_market_urls',
                             return_value=set()), \
                patch.object(self.application_module, '_public_host_addresses',
                             return_value=()):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        self.assertEqual(res.status_code, 200, res.get_json())
        payload = res.get_json()
        self.assertTrue(payload.get('success'))
        self.assertTrue(payload.get('searchVerified'))
        self.assertTrue(payload.get('partial'))
        self.assertEqual(payload.get('noEvidenceCount'), 6)
        self.assertEqual(payload.get('missingPriceCount'), 6)

    def test_market_competitors_combines_citations_across_rounds(self):
        """Expansion rounds feed the same evidence pool — a page retrieved in
        round two still reaches its competitor's source list."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        first = {
            'choices': [{'message': {
                'content': json.dumps({'competitors': [
                    {'name': 'مجمع الفرسان', 'project_type': 'سكني'}]},
                    ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/fursan',
                    'title': 'مجمع الفرسان — المطور', 'content': ''}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        second = {
            'choices': [{'message': {
                'content': json.dumps({'competitors': [
                    {'name': 'واحة الريان', 'project_type': 'سكني'},
                    {'name': 'برج السدرة', 'project_type': 'سكني'},
                    {'name': 'مشروع النخبة', 'project_type': 'سكني'},
                    {'name': 'مجمع الياسمين', 'project_type': 'سكني'}]},
                    ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/alrayan',
                    'title': 'واحة الريان', 'content': ''}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        verify = {
            'choices': [{'message': {'content': '{"exists": true}', 'annotations': []}}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        responses = [first, second]

        def fake_model(*_args, **_kwargs):
            return (responses.pop(0), '') if responses else (verify, '')

        module = self.application_module
        with patch.object(module, '_call_market_study_model', side_effect=fake_model), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_public_host_addresses', return_value=()):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        self.assertEqual(res.status_code, 200, res.get_json())
        payload = res.get_json()
        rows = {row['name']: row for row in payload['competitors']}
        self.assertIn('https://developer.example/fursan',
                      rows['مجمع الفرسان'].get('source_urls') or [])
        self.assertIn('https://developer.example/alrayan',
                      rows['واحة الريان'].get('source_urls') or [])

    def test_market_competitors_surfaces_provider_error(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        failed = ({'error': {'message': 'provider finished with MALFORMED_FUNCTION_CALL'}},
                  'provider finished with MALFORMED_FUNCTION_CALL')
        with patch.object(self.application_module, '_call_market_study_model',
                          return_value=failed):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        payload = res.get_json()
        self.assertFalse(payload.get('success'))
        self.assertIn('MALFORMED_FUNCTION_CALL', payload.get('providerError') or '')

    def test_market_competitors_tenant_key_gate_surfaces_at_job_level(self):
        """A strict-mode refusal in the per-competitor verify calls must reach
        the job's providerError — and a deterministic gate error must stop the
        remaining query angles instead of burning every retry."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        names = ['مجمع الفرسان', 'واحة الريان', 'برج السدرة', 'مشروع النخبة',
                 'مجمع الياسمين']
        grounded = {
            'choices': [{'message': {
                'content': json.dumps({'competitors': [
                    {'name': name, 'project_type': 'سكني'} for name in names]},
                    ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://sabq.org/article/x', 'title': 'سوق جدة',
                    'content': ''}}],
            }}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        gate = ({'error': {'message': 'لا يوجد مفتاح AI مفعل لهذه الشركة',
                           'error_code': 'NO_TENANT_KEY'}},
                'لا يوجد مفتاح AI مفعل لهذه الشركة')
        calls = []

        def fake_model(*_args, **_kwargs):
            calls.append(1)
            return (grounded, '') if not calls[1:] else gate

        module = self.application_module
        with patch.object(module, '_call_market_study_model', side_effect=fake_model), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_public_host_addresses', return_value=()):
            res = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate',
            })
        payload = res.get_json()
        self.assertTrue(payload.get('success'))
        self.assertIn('مفتاح', payload.get('providerError') or '')
        rows = payload.get('competitors') or []
        self.assertTrue(all(row.get('verify_state') == 'search_not_run' for row in rows))
        # 1 main call + 2 attempts per row (the gate break skips the second
        # query angle) + the logo-discovery batch — not 4+ per row.
        self.assertLessEqual(len(calls), 13)

    def test_pinned_https_get_follows_only_same_site_redirects(self):
        module = self.application_module
        redirect = Mock(status=301, headers={'Location': '/ar/home'})
        landing = Mock(status=200, headers={})
        opened = []

        def fake_open(parsed, _addresses):
            opened.append(parsed.geturl())
            return Mock(), (redirect if len(opened) == 1 else landing)

        with patch.object(module, '_public_host_addresses', return_value=('203.0.113.10',)), \
                patch.object(module, '_open_pinned_https', side_effect=fake_open):
            _pool, response, final_url = module._pinned_https_get('https://developer.example/')
        self.assertIs(response, landing)
        self.assertEqual(final_url, 'https://developer.example/ar/home')
        redirect.release_conn.assert_called_once()

        offsite = Mock(status=302, headers={'Location': 'https://evil.example/x'})
        with patch.object(module, '_public_host_addresses', return_value=('203.0.113.10',)), \
                patch.object(module, '_open_pinned_https', return_value=(Mock(), offsite)):
            pool, _response, outcome = module._pinned_https_get('https://developer.example/')
        self.assertIsNone(pool)
        self.assertEqual(outcome, 'off_site_redirect')
        offsite.release_conn.assert_called_once()

        downgrade = Mock(status=301, headers={'Location': 'http://developer.example/x'})
        with patch.object(module, '_public_host_addresses', return_value=('203.0.113.10',)), \
                patch.object(module, '_open_pinned_https', return_value=(Mock(), downgrade)):
            pool, _response, outcome = module._pinned_https_get('https://developer.example/')
        self.assertIsNone(pool)
        self.assertEqual(outcome, 'invalid_url')

    def test_market_source_priority_matches_owner_order(self):
        import market_study
        expected = {
            1: [
                'الهيئة العامة للعقار rega.gov.sa',
                'منصة المؤشرات العقارية rei.rega.gov.sa — صفقات البيع المنفذة rei.rega.gov.sa/ar/advanced-search/deals ومتوسط سعر المتر حسب الحي ونوع العقار',
                'المؤشرات اللحظية rei.rega.gov.sa/ar/advanced-search/live — أسعار السوق الحالية',
                'مؤشر سوق الإيجار التفصيلي rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator — ومقارنة الأحياء rei.rega.gov.sa/ar/advanced-search/rental-market/comparison',
                'معروض الإعلانات rei.rega.gov.sa/ar/advanced-search/ads-supply-market — أسعار الطلب المعروضة',
                'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول إيجار الوحدات السكنية والتجارية حسب المدينة والحي',
                'السجل العقاري rer.sa وبيانات وزارة العدل moj.gov.sa المتاحة',
                'شبكة إيجار ejar.sa',
                'الهيئة العامة للإحصاء stats.gov.sa',
                'منصة البيانات المفتوحة السعودية open.data.gov.sa',
                'وزارة البلديات والإسكان momah.gov.sa',
                'منصة بلدي balady.gov.sa',
                'الأمانة التابعة للمدينة',
                'كود البناء السعودي sbc.gov.sa',
                'البنك المركزي السعودي sama.gov.sa',
                'برنامج وافي red.rega.gov.sa — مشاريع البيع والتأجير على الخارطة المرخصة',
                'منصة سكني sakani.sa',
                'الشركة الوطنية للإسكان NHC nhc.sa',
            ],
            2: [
                'موقع المشروع الرسمي', 'موقع المطور الرسمي', 'موقع المشغل الرسمي',
                'موقع العلامة الفندقية', 'كتيب المشروع الرسمي', 'بيانات البيع الرسمية',
                'بيانات تداول للشركات والصناديق العقارية', 'الإعلانات الرسمية للمطور',
            ],
            3: ['CBRE cbre.sa', 'JLL jll.com/en-sa', 'Knight Frank knightfrank.com.sa',
                'Colliers colliers.com/en-sa', 'Savills savills.me',
                'ValuStrat valustrat.com', 'Deloitte deloitte.com/middle-east',
                'PwC pwc.com/m1', 'KPMG kpmg.com/sa', 'EY ey.com',
                'STR str.com أو CoStar costar.com للفنادق'],
            4: ['منصة عقار aqar.fm', 'بيوت السعودية bayut.sa', 'وصلت wasalt.sa',
                'تطبيق ديل dealapp.sa', 'منصات المسوقين العقاريين المرخصين'],
            5: ['Google Maps للمواقع والمسافات والخدمات maps.google.com',
                'Google Places للتقييمات والحركة المحيطة',
                'المواقع الإخبارية الموثوقة',
                'وكالة الأنباء السعودية spa.gov.sa', 'البيانات الصحفية الرسمية'],
        }
        self.assertEqual(market_study.SOURCE_PRIORITY, expected)
        expected_type_sources = {
            'سكني': [
                'منصة المؤشرات العقارية rei.rega.gov.sa/ar/advanced-search — صفقات البيع المنفذة deals ومؤشر سوق الإيجار rental-market',
                'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data',
                'الهيئة العامة للإحصاء stats.gov.sa',
                'البنك المركزي السعودي sama.gov.sa', 'وافي red.rega.gov.sa',
                'سكني sakani.sa وNHC nhc.sa', 'الأمانة وبلدي balady.gov.sa',
                'المواقع الرسمية للمطورين',
                'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
                'منصات الإعلانات العقارية aqar.fm وbayut.sa وwasalt.sa',
                'Google Maps للموقع والخدمات فقط',
            ],
            'تجاري': [
                'منصة المؤشرات العقارية rei.rega.gov.sa/ar/advanced-search — صفقات البيع المنفذة deals ومؤشر سوق الإيجار rental-market — وشبكة إيجار ejar.sa',
                'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول الوحدات التجارية',
                'الهيئة العامة للإحصاء stats.gov.sa', 'وزارة التجارة mc.gov.sa',
                'الأمانة وبلدي balady.gov.sa', 'البنك المركزي السعودي sama.gov.sa',
                'المواقع الرسمية للمراكز والمشروعات التجارية',
                'تداول saudiexchange.sa وتقارير الصناديق العقارية',
                'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa وSavills savills.me',
                'منصات التأجير والإعلانات aqar.fm وbayut.sa وwasalt.sa',
                'Google Maps وGoogle Places للخدمات والتقييمات',
            ],
            'فندقي': [
                'وزارة السياحة mt.gov.sa',
                'الهيئة العامة للإحصاء stats.gov.sa وإحصاءات المنشآت السياحية',
                'الهيئة العامة للطيران المدني gaca.gov.sa',
                'الجهات الرسمية للفعاليات والسياحة في المدينة',
                'المواقع الرسمية للفنادق والمشغلين', 'STR str.com أو CoStar costar.com',
                'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
                'مواقع الحجز لمقارنة السعر في تاريخ محدد فقط',
                'Google Maps للتقييمات والموقع والخدمات',
            ],
            'صناعي ولوجستي': [
                'وزارة الصناعة والثروة المعدنية mim.gov.sa',
                'الهيئة السعودية للمدن الصناعية ومناطق التقنية مدن modon.gov.sa',
                'خرائط مدن GIS',
                'هيئة المدن والمناطق الاقتصادية الخاصة ecza.gov.sa',
                'الهيئة العامة للإحصاء stats.gov.sa',
                'الهيئة العامة للموانئ mawani.gov.sa',
                'الهيئة العامة للطيران المدني للشحن الجوي gaca.gov.sa',
                'وزارة النقل والخدمات اللوجستية mot.gov.sa', 'الأمانة وبلدي balady.gov.sa',
                'المواقع الرسمية للمدن الصناعية والمشروعات',
                'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
                'منصات المستودعات والعقارات الصناعية',
            ],
        }
        self.assertEqual(market_study.TYPE_SOURCE_PRIORITY, expected_type_sources)
        self.assertEqual(market_study.catalog_payload()['sourcePriority'], expected)
        self.assertEqual(market_study.catalog_payload()['typeSourcePriority'], expected_type_sources)
        prompt = market_study.build_consultant_system_prompt()
        self.assertIn('ابدأ بالمستوى الأول، ولا تنتقل إلى مستوى أدنى', prompt)
        self.assertIn('تعامل مع أسعار منصات الإعلانات باعتبارها أسعار طلب وليست صفقات منفذة.', prompt)

    def test_target_audience_options_do_not_include_other(self):
        import market_study
        self.assertNotIn('أخرى', market_study.GENERAL_TARGET_AUDIENCE)
        self.assertNotIn('أخرى', market_study.target_audience_options('سكني'))
        self.assertNotIn('أخرى', market_study.target_audience_options('تجاري', 'مكاتب'))
        self.assertEqual(
            market_study.activity_class_options('سكني'),
            [item['label'] for item in market_study.PROJECT_LEVELS]
        )

    def test_mixed_use_unlocks_selected_subtypes(self):
        import market_study
        self.assertEqual(
            market_study.analysis_kind_for_project('متعدد الاستخدامات', '', ['مكاتب', 'فندق']),
            ['مكاتب', 'فندقي']
        )
        self.assertEqual(
            market_study.activity_class_options('متعدد الاستخدامات', '', ['مكاتب', 'فندق']),
            market_study.ACTIVITY_CLASS_BY_TYPE['مكاتب'] + [
                option for option in market_study.ACTIVITY_CLASS_BY_TYPE['فندقي']
                if option not in market_study.ACTIVITY_CLASS_BY_TYPE['مكاتب']
            ]
        )

    def test_market_study_normalizes_swot_independently_of_summary(self):
        import market_study
        parsed = market_study.normalize_summary({
            'summary': {'market_definition': 'سوق سكني في الرياض', 'decision': 'فرصة واعدة بشروط'},
            'swot': {
                'strengths': 'موقع على طريق رئيسي',
                'weaknesses': 'مساحة الأرض محدودة',
                'opportunities': 'نقص المعروض المناسب',
                'threats': 'مشروعات جديدة قريبة',
            },
            'decision': 'فرصة واعدة بشروط',
            'sources': [{'name': 'الهيئة العامة للإحصاء', 'url': 'https://www.stats.gov.sa'}],
        })
        self.assertEqual(parsed['title'], 'الملخص التنفيذي لسوق المشروع')
        self.assertEqual(parsed['swot']['strengths'], 'موقع على طريق رئيسي')
        self.assertEqual(parsed['swot']['threats'], 'مشروعات جديدة قريبة')
        self.assertEqual(parsed['summary']['market_definition'], 'سوق سكني في الرياض')
        self.assertEqual(parsed['summary']['city_position'], market_study.MISSING_VALUE_PHRASE)
        self.assertEqual(parsed['decision'], 'فرصة واعدة بشروط')
        prose = market_study.normalize_summary({
            'summary': {
                'market_definition': 'سوق الضيافة الفاخرة في جدة',
                'demand': 'ينمو الطلب على الواجهة البحرية',
            },
            'one_block_summary': 'سوق الضيافة الفاخرة في جدة ينمو مع الطلب على الواجهة البحرية.',
            'decision': 'فرصة قوية',
        })
        self.assertEqual(prose['summary']['demand'], 'ينمو الطلب على الواجهة البحرية')
        self.assertEqual(prose['one_block_summary'], 'سوق الضيافة الفاخرة في جدة ينمو مع الطلب على الواجهة البحرية.')
        self.assertIn('ابدأ المخرجات بعنوان: الملخص التنفيذي لسوق المشروع.', market_study.build_summary_user_prompt({}, []))
        self.assertIn('في حدود 350 كلمة', market_study.build_summary_user_prompt({}, []))
        self.assertIn('على ألا تقل عن 300 كلمة', market_study.build_summary_user_prompt({}, []))
        self.assertIn('مصادر حالية إن وُجدت', market_study.build_summary_user_prompt({}, []))
        summary_prompt = market_study.build_summary_user_prompt({}, [])
        self.assertIn('تحليل السوق التفصيلي داخل summary على شكل محاور منظمة', summary_prompt)
        self.assertIn('one_block_summary باعتباره الملخص التنفيذي لسوق المشروع', summary_prompt)
        self.assertIn('"market_definition": "تحليل محور تعريف السوق"', summary_prompt)

    def test_contact_section_and_fields_registered_and_piped(self):
        """Contact information section and its 7 fields are registered in schema and piped to slide engine."""
        import slide_engine

        # Section exists in FIELD_SECTIONS
        contact_sec = next((s for s in db.FIELD_SECTIONS if s['key'] == 'contact'), None)
        self.assertIsNotNone(contact_sec)
        self.assertEqual(contact_sec['label'], 'بيانات التواصل')

        # 7 prebuilt fields exist in PREBUILT_FIELDS
        prebuilt_by_key = {f['key']: f for f in db.PREBUILT_FIELDS}
        expected_keys = [
            'contact_name', 'contact_position', 'contact_email', 'contact_phone',
            'contact_website', 'contact_address', 'contact_social_media'
        ]
        for key in expected_keys:
            self.assertIn(key, prebuilt_by_key)
            self.assertEqual(prebuilt_by_key[key]['section_key'], 'contact')

        # slide_engine._contact_facts formats all 7 fields
        facts = slide_engine._contact_facts({
            'contact_name': 'سعد الأحمد',
            'contact_position': 'المدير التنفيذي',
            'contact_phone': '0500000000',
            'contact_email': 'info@project.sa',
            'contact_website': 'https://project.sa',
            'contact_address': 'الرياض - طريق الملك فهد',
            'contact_social_media': '@project_sa',
        })
        self.assertIn('سعد الأحمد', facts)
        self.assertIn('المدير التنفيذي', facts)
        self.assertIn('0500000000', facts)
        self.assertIn('info@project.sa', facts)
        self.assertIn('https://project.sa', facts)
        self.assertIn('الرياض - طريق الملك فهد', facts)
        self.assertIn('@project_sa', facts)

        # When no contact data is entered, _contact_facts returns empty string
        empty_facts = slide_engine._contact_facts({})
        self.assertEqual(empty_facts, '')

        # Closing slide prompt instructions
        closing_msg = slide_engine.build_slide_user_msg({'type': 'closing', 'title': 'الخاتمة'}, 10, 10, {}, {})
        self.assertIn('اقتصر على شكر موجز واسم المشروع', closing_msg)
        self.assertIn('دون أي بيانات وهمية', closing_msg)
        self.assertIn('استخدم الصورة الرئيسية بوضوح', closing_msg)

        # Form renders contact section at the end of the form and sidebar
        index_source = read_frontend_text()
        self.assertIn("renderFormSection('contact')", index_source)
        exec_pos = index_source.index('addExecutiveContentSection(form);')
        contact_pos = index_source.index("renderFormSection('contact')", exec_pos)
        self.assertGreater(contact_pos, exec_pos)

    def test_empty_sections_are_completely_omitted_from_prompt_and_deck_plan(self):
        """Any section with no real data is completely excluded from prompt facts and deck plan."""
        import slide_engine

        basic_only_draft = {
            'project_name': 'مشروع تجريبي',
            'project_type': 'تجاري',
            'financial_study_model': '{}',
            'market_study_data': '{}',
            'team_selection': '{}',
            'executive_content': '{}',
            'timeline_table_data': '[]',
        }

        # 1. Facts omit all empty sections
        facts = slide_engine.build_project_facts(basic_only_draft)
        self.assertIn('### معلومات أساسية', facts)
        self.assertNotIn('### الدراسة المالية', facts)
        self.assertNotIn('### دراسة السوق', facts)
        self.assertNotIn('### فريق العمل', facts)
        self.assertNotIn('### المحتوى التنفيذي المعتمد', facts)
        self.assertNotIn('### بيانات التواصل المعتمدة للخاتمة', facts)

        # 2. Deck plan omits all empty sections and their dividers
        plan = slide_engine.normalize_presentation_plan({}, project_data=basic_only_draft, images={})
        emitted_sections = {s.get('section_key') for s in plan['slides']}
        self.assertNotIn('financial', emitted_sections)
        self.assertNotIn('team', emitted_sections)
        self.assertNotIn('market', emitted_sections)
        self.assertNotIn('timeline', emitted_sections)
        self.assertNotIn('swot_risks', emitted_sections)
        self.assertNotIn('plans', emitted_sections)
        self.assertNotIn('exterior', emitted_sections)
        self.assertNotIn('interior', emitted_sections)
        self.assertNotIn('executive_summary', emitted_sections)

        # 3. Index slide entries match only emitted sections
        index_slide = next(s for s in plan['slides'] if s.get('type') == 'index')
        index_titles = [e['title'] for e in index_slide.get('index_entries', [])]
        self.assertNotIn('الدراسة المالية', index_titles)
        self.assertNotIn('فريق العمل', index_titles)
        self.assertNotIn('تحليل السوق', index_titles)
        self.assertNotIn('الجدول الزمني', index_titles)
        self.assertIn('الخاتمة', index_titles)

    def test_heatmap_polarity_and_three_tier_colors(self):
        engine = self.application_module.slide_engine
        sample_rows = [
            {
                'السيناريو': 'متحفظ',
                'إجمالي الإيرادات': '125,000,000',
                'إجمالي تكلفة المشروع': '110,000,000',
                'صافي الربح': '15,000,000',
                'ROI كامل الدورة': '13.6%',
                'Project IRR كامل الدورة': '11.2%',
                'Equity IRR كامل الدورة': '14.0%',
                'فترة الاسترداد': '7.2 سنة'
            },
            {
                'السيناريو': 'أساسي',
                'إجمالي الإيرادات': '150,000,000',
                'إجمالي تكلفة المشروع': '105,000,000',
                'صافي الربح': '45,000,000',
                'ROI كامل الدورة': '42.8%',
                'Project IRR كامل الدورة': '16.5%',
                'Equity IRR كامل الدورة': '21.0%',
                'فترة الاسترداد': '5.0 سنة'
            },
            {
                'السيناريو': 'متفائل',
                'إجمالي الإيرادات': '180,000,000',
                'إجمالي تكلفة المشروع': '100,000,000',
                'صافي الربح': '80,000,000',
                'ROI كامل الدورة': '80.0%',
                'Project IRR كامل الدورة': '22.0%',
                'Equity IRR كامل الدورة': '28.5%',
                'فترة الاسترداد': '3.8 سنة'
            }
        ]
        res = engine._extract_heatmap_chart_data({'rows': sample_rows})
        self.assertIn('matrix', res)
        self.assertIn('columns', res)
        self.assertIn('legend', res)
        self.assertIn('html_matrix', res)
        self.assertEqual(len(res['matrix']), 7)

        # 1. Higher is better (Revenue, Profit, ROI, Project IRR, Equity IRR)
        rev = next(r for r in res['matrix'] if r['key'] == 'revenue')
        self.assertTrue(rev['higher_is_better'])
        self.assertEqual(rev['conservative_level'], 'worst')
        self.assertEqual(rev['base_level'], 'medium')
        self.assertEqual(rev['optimistic_level'], 'best')

        # 2. Lower is better (Cost, Payback)
        cost = next(r for r in res['matrix'] if r['key'] == 'cost')
        self.assertFalse(cost['higher_is_better'])
        self.assertEqual(cost['conservative_level'], 'worst')  # 110M is highest cost -> worst
        self.assertEqual(cost['base_level'], 'medium')        # 105M is middle -> medium
        self.assertEqual(cost['optimistic_level'], 'best')    # 100M is lowest cost -> best

        pb = next(r for r in res['matrix'] if r['key'] == 'payback')
        self.assertFalse(pb['higher_is_better'])
        self.assertEqual(pb['conservative_level'], 'worst')   # 7.2 years is longest -> worst
        self.assertEqual(pb['base_level'], 'medium')          # 5.0 years is middle -> medium
        self.assertEqual(pb['optimistic_level'], 'best')      # 3.8 years is shortest -> best

        # 3. Reverse cost scenario where conservative spends less
        reverse_rows = [
            {'السيناريو': 'متحفظ', 'إجمالي تكلفة المشروع': '80,000,000'},
            {'السيناريو': 'أساسي', 'إجمالي تكلفة المشروع': '100,000,000'},
            {'السيناريو': 'متفائل', 'إجمالي تكلفة المشروع': '120,000,000'},
        ]
        rev_res = engine._extract_heatmap_chart_data({'rows': reverse_rows})
        rev_cost = next(r for r in rev_res['matrix'] if r['key'] == 'cost')
        self.assertEqual(rev_cost['conservative_level'], 'best')   # 80M is lowest -> best
        self.assertEqual(rev_cost['base_level'], 'medium')         # 100M is middle -> medium
        self.assertEqual(rev_cost['optimistic_level'], 'worst')    # 120M is highest -> worst

        # 4. Non-numeric payback "لا يسترد"
        non_num_rows = [
            {'السيناريو': 'متحفظ', 'فترة الاسترداد': 'لا يسترد'},
            {'السيناريو': 'أساسي', 'فترة الاسترداد': '5.0 سنة'},
            {'السيناريو': 'متفائل', 'فترة الاسترداد': '3.8 سنة'},
        ]
        non_num_res = engine._extract_heatmap_chart_data({'rows': non_num_rows})
        non_num_pb = next(r for r in non_num_res['matrix'] if r['key'] == 'payback')
        self.assertEqual(non_num_pb['conservative_level'], 'worst')
        self.assertEqual(non_num_pb['base_level'], 'medium')
        self.assertEqual(non_num_pb['optimistic_level'], 'best')

        # 5. Zero emojis, zero icons in generated html_matrix and labels
        self.assertIsNone(re.search(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]', res['html_matrix']))

    def test_heatmap_slide_keeps_all_financial_metrics_inside_card(self):
        engine = self.application_module.slide_engine
        rows = [
            {'السيناريو': 'متحفظ', 'إجمالي الإيرادات': '125,000,000', 'إجمالي تكلفة المشروع': '110,000,000',
             'صافي الربح': '15,000,000', 'ROI كامل الدورة': '13.6%', 'Project IRR كامل الدورة': '11.2%',
             'Equity IRR كامل الدورة': '14.0%', 'فترة الاسترداد': '7.2 سنة'},
            {'السيناريو': 'أساسي', 'إجمالي الإيرادات': '150,000,000', 'إجمالي تكلفة المشروع': '105,000,000',
             'صافي الربح': '45,000,000', 'ROI كامل الدورة': '42.8%', 'Project IRR كامل الدورة': '16.5%',
             'Equity IRR كامل الدورة': '21.0%', 'فترة الاسترداد': '5.0 سنة'},
            {'السيناريو': 'متفائل', 'إجمالي الإيرادات': '180,000,000', 'إجمالي تكلفة المشروع': '100,000,000',
             'صافي الربح': '80,000,000', 'ROI كامل الدورة': '80.0%', 'Project IRR كامل الدورة': '22.0%',
             'Equity IRR كامل الدورة': '28.5%', 'فترة الاسترداد': '3.8 سنة'},
        ]
        slide_html = engine._build_sol_heatmap_slide(
            {'title': 'مقارنة السيناريوهات المالية', 'chart_type': 'heatmap'},
            {'project_name': 'مشروع الاختبار', 'financial_study_model': {'tables': {'sensitivityTable': rows}}},
            {},
        )

        self.assertEqual(slide_html.count('<tr>'), 8)  # header plus all seven metric rows
        for metric in ('إجمالي الإيرادات', 'إجمالي تكلفة المشروع', 'صافي الربح', 'ROI', 'Project IRR', 'Equity IRR', 'فترة الاسترداد'):
            self.assertIn(metric, slide_html)
        self.assertNotIn('max-height:440px;overflow:hidden;', slide_html)
        self.assertIn('max-height:510px;overflow:visible;', slide_html)
