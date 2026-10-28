class MeetingRequirementsTestsPart16(MeetingRequirementsTests):

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
        self.assertNotIn('<textarea data-field="note" rows="2">', index_source)
        self.assertNotIn('<th>الموثوقية</th>', index_source)
        self.assertNotIn('<th>تاريخ الوصول</th>', index_source)
        self.assertIn("tr.querySelectorAll('input,select,textarea')", index_source)
        self.assertIn('<select data-field="classification">', index_source)
        self.assertIn('<td data-field="logo_cell"></td>', index_source)
        # The currency travels with the row's own price, so the cell carries the
        # row currency rather than one hardcoded code.
        self.assertIn('data-currency="', index_source)
        self.assertIn("data-currency=\"' + escapeHtml(rowCurrency) + '\"",
                      index_source)
        # The placeholder names the row's own currency, not a fixed riyal tag.
        self.assertIn("const priceFromPlaceholder = 'من (' + currencyLabel + ')';",
                      index_source)
        self.assertIn("escapeHtml(priceFromPlaceholder)", index_source)
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
        self.assertIn('run_browse_agent', app_source)
        # Two owner-ordered native calls: the summary researcher's plugin and
        # the competitor fallback for a local search that never ran. The old
        # 'openrouter:web_search' tool and the paid Exa layer are gone.
        self.assertNotIn('openrouter:web_search', app_source)
        self.assertEqual(app_source.count("'id': 'web'"), 2)
        self.assertIn("browse_kwargs['plugins'] = [{'id': 'web', 'max_results': 5}]",
                      app_source)
        self.assertIn('_native_search_fallback(', app_source)
        self.assertIn('_native_fallback_needed(', app_source)
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

    def test_market_study_price_currency_survives_and_travels_with_the_price(self):
        """A Booking page priced in euros used to lose its figure entirely —
        the row had no currency slot, so «120 EUR» could only be written as a
        fake SAR number or dropped. normalize converts the figure to whole
        riyals and keeps the printed amount and code beside it in the price
        cache, fill-mode merge moves the tag only alongside a price it labels,
        and the prompt schema declares the field."""
        import market_study
        with patch.object(market_study, 'price_fx_to_sar', return_value=4.2):
            row = market_study.normalize_competitor_row({
                'name': 'فندق بوكينج',
                'operation_type': 'تشغيل فندقي',
                'price_type': 'سعر الليلة',
                'price_value': '120',
                'price_currency': 'يورو',
            })
            self.assertEqual(row['price_value'], '504')
            self.assertEqual(row['price_currency'], 'SAR')
            self.assertEqual(row['price_cache']['original_currency'], 'EUR')
            self.assertEqual(row['price_cache']['original_price_value'], '120')
            aliased = market_study.normalize_competitor_row({
                'name': 'فندق الدولار',
                'price': {'type': 'سعر الليلة', 'value': '95', 'currency': 'US$'},
            })
            self.assertEqual(aliased['price_currency'], 'SAR')
            self.assertEqual(aliased['price_cache']['original_currency'], 'USD')
            merged, _added, _updated = market_study.merge_generated_competitors(
                [{'id': 'm1', 'name': 'فندق بوكينج', 'price_value': '900'}],
                [{'id': 'm1', 'name': 'فندق بوكينج', 'price_currency': 'EUR'}],
                mode='fill')
            # The tag travels only with a price it labels; the client's SAR
            # figure is never renamed as a foreign amount.
            self.assertEqual(merged[0]['price_value'], '900')
            self.assertEqual(merged[0].get('price_currency'), 'SAR')
            merged2, _added2, _updated2 = market_study.merge_generated_competitors(
                [{'id': 'm2', 'name': 'فندق آخر'}],
                [{'id': 'm2', 'name': 'فندق آخر', 'price_value': '480',
                  'price_currency': 'USD'}],
                mode='fill')
            # A foreign figure fills the empty cell as whole riyals, with the
            # printed amount and code kept in the price cache.
            self.assertEqual(merged2[0]['price_value'], '2016')
            self.assertEqual(merged2[0]['price_currency'], 'SAR')
            self.assertEqual(merged2[0]['price_cache']['original_currency'], 'USD')
            self.assertEqual(merged2[0]['price_cache']['original_price_value'], '480')
        prompt = market_study.build_competitors_user_prompt({}, [], mode='generate')
        self.assertIn('price_currency', prompt)

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

    def test_market_search_layer_is_the_browse_agent(self):
        """Every market web task rides one self-hosted Chromium agent driven by
        the task's own model, with two owner-ordered native calls: the summary
        researcher's plugin search and the competitor fallback used only when
        the local search layer never ran. The old paid layer must not return."""
        module = self.application_module
        self.assertFalse(hasattr(module, '_call_market_study_model'))
        self.assertFalse(hasattr(module, 'MARKET_SEARCH_ENGINE'))
        app_source = read_module_source('app.py')
        # The provider-native server tool is gone; the two sanctioned native
        # searches are the summary researcher's plugin call and the gated
        # competitor fallback. A third occurrence is the deleted paid layer.
        self.assertNotIn('openrouter:web_search', app_source)
        self.assertEqual(app_source.count("'id': 'web'"), 2)
        self.assertIn("browse_kwargs['plugins'] = [{'id': 'web', 'max_results': 5}]",
                      app_source)
        self.assertIn('_native_search_fallback(', app_source)
        self.assertIn('_native_fallback_needed(', app_source)
        self.assertIn('_browse_agent_call(', app_source)

    def test_browse_agent_call_sends_task_model_and_full_task(self):
        """``_browse_agent_call`` is the seam: it composes system+user into the
        agent task and forwards the market model plus the caller's usage ctx."""
        import agent
        module = self.application_module
        seen = {}

        def fake_run(task, **kwargs):
            seen['task'] = task
            seen.update(kwargs)
            return {'choices': [{'message': {'content': '{}'}}]}

        ctx = {'tenant_id': 't-1', 'flow': 'market'}
        with patch.object(agent, 'run_browse_agent', side_effect=fake_run):
            res = module._browse_agent_call('SYS-BRIEF', 'USER-ASK', ctx)
        self.assertIn('SYS-BRIEF', seen['task'])
        self.assertIn('USER-ASK', seen['task'])
        self.assertEqual(seen.get('model'), module.MARKET_STUDY_MODEL)
        self.assertIs(seen.get('usage_ctx'), ctx)
        self.assertEqual(
            res['choices'][0]['message']['content'], '{}')

        # A module-level failure still comes back as an explicit error dict,
        # never an exception the callers must catch.
        with patch.object(agent, 'run_browse_agent',
                          side_effect=RuntimeError('launch_failed')):
            res = module._browse_agent_call('s', 'u')
        self.assertIn('browse_agent', res['error']['message'])

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
        self.assertIn("market_study.apply_search_citations(merged, evidence_urls)", app_source)

    def test_portal_homepage_links_resolve_to_the_dataset_page(self):
        import market_study
        # sakani.sa is the mapped portal: a homepage citation resolves to the
        # fixed dataset view. rei.rega.gov.sa is deliberately unmapped — its
        # advanced-search grids are Nafath-gated, so a homepage stays a
        # homepage instead of resolving into a login shell.
        rental = {
            'name': 'مجمع إيجاري',
            'operation_type': 'إيجار',
            'source_url': 'https://sakani.sa',
            'source_urls': ['https://sakani.sa'],
            'field_sources': {'price_value': ['https://sakani.sa']},
            'row_source': 'ai',
        }
        market_study.apply_search_citations([rental], [])
        self.assertEqual(rental['source_url'], 'https://sakani.sa/reports-and-data')
        self.assertEqual(rental['source_urls'], ['https://sakani.sa/reports-and-data'])
        self.assertEqual(
            rental['field_sources']['price_value'], ['https://sakani.sa/reports-and-data'])
        self.assertTrue(all(
            not market_study.is_generic_source_homepage(url) for url in rental['source_urls']))
        # A retrieved page on the same host still wins over the canonical map.
        retrieved = ['https://sakani.sa/reports-and-data?city=jeddah']
        cited = {
            'name': 'برج', 'operation_type': 'إيجار',
            'source_url': 'https://sakani.sa', 'row_source': 'ai',
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
            'name': 'برج', 'operation_type': 'إيجار',
            'source_url': 'https://sakani.sa',
            'source_urls': ['https://sakani.sa', 'https://dev.sa/proj/1'],
        }
        market_study.canonicalize_competitor_source_urls(merged)
        self.assertEqual(
            merged['source_urls'][0], 'https://sakani.sa/reports-and-data')
        self.assertEqual(
            merged['source_url'], 'https://sakani.sa/reports-and-data')
        # And the gated REGA grids never come back through normalization.
        gated = {
            'name': 'برج', 'operation_type': 'بيع',
            'source_url': 'https://rei.rega.gov.sa/ar', 'row_source': 'ai',
        }
        market_study.apply_search_citations([gated], [])
        self.assertEqual(gated['source_url'], 'https://rei.rega.gov.sa/ar')

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
        with patch.object(module, '_browse_agent_call', return_value=response):
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
        with patch.object(module, '_browse_agent_call', return_value=ghost):
            module._verify_competitor_row(rejected, {'city': 'جدة'}, {})
        self.assertFalse(rejected.get('price_value'))
        # An evidence-backed price from the main pass is never overwritten.
        filled = {'name': 'مشروع علو الرحاب', 'operation_type': 'إيجار',
                  'price_value': '30000', 'row_source': 'ai'}
        with patch.object(module, '_browse_agent_call', return_value=response):
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
        with patch.object(module, '_browse_agent_call', return_value=foreign_res):
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
        with patch.object(module, '_browse_agent_call', return_value=silent):
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
        # The browse agent is the only search layer — its per-task budgets are
        # explicit call-site constants, not provider-side search settings.
        self.assertIn('_COMPETITORS_SEARCH_BUDGET', app_source)
        self.assertIn('search_budget=', app_source)
        # The hosted web plugin belongs to the browse agent's own transport; the
        # retired one-shot web_search call (and its engine switch) stays gone.
        self.assertNotIn('openrouter:web_search', app_source)
        self.assertNotIn('MARKET_SEARCH_ENGINE', app_source)
