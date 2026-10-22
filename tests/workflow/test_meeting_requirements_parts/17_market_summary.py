class MeetingRequirementsTestsPart17(MeetingRequirementsTests):

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
        self.assertIn('800 مليون ريال', prompt)
        self.assertIn('45 مليون ريال', prompt)
        self.assertIn('18.3%', prompt)
        self.assertIn('طريق الملك فهد', prompt)
        self.assertIn('مجمع الراشد (تسوق)', prompt)
        self.assertIn('annualRent = إيجار سنوي', prompt)
        self.assertIn('طبيعة الإيرادات في بيانات المشروع ملزمة', prompt)
        # A project with no financial data must not render the block at all.
        bare = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        self.assertNotIn('مؤشرات الدراسة المالية', bare)

    def test_market_fatal_refusal_reports_credit(self):
        """A deterministic wallet/key refusal from the agent keeps its fatal
        code through _execute_market_competitors — insufficient_credit, not a
        generic generation failure."""
        module = self.application_module
        fatal = {'error': {'fatal': True, 'message': 'استُنفد الرصيد',
                           'error_code': 'INSUFFICIENT_CREDITS',
                           'http_status': 402}}
        with patch.object(module, '_browse_agent_call', return_value=dict(fatal)):
            result = module._execute_market_competitors(
                {'projectType': 'سكني', 'city': 'الرياض', 'mode': 'generate'})
        self.assertFalse(result['success'])
        self.assertEqual(result.get('failureReason'), 'insufficient_credit')
        self.assertIn('الرصيد', result.get('providerError') or result.get('error') or '')

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
        with patch.object(self.application_module, '_browse_agent_call',
                          return_value=fake_response), \
                patch.object(self.application_module, '_run_market_source_plan',
                             return_value=None), \
                patch.object(self.application_module, '_new_evidence_pool',
                             return_value=None), \
                patch.object(self.application_module, '_verify_competitor_rows',
                             return_value=None), \
                patch.object(self.application_module, '_auto_import_competitor_logos',
                             return_value=None), \
                patch.object(self.application_module, '_verify_market_urls',
                             return_value=set()):
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
        with patch.object(self.application_module, '_browse_agent_call',
                          return_value=memory_response):
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
        with patch.object(self.application_module, '_browse_agent_call',
                          return_value=verified_response), \
                patch.object(self.application_module, '_run_market_source_plan',
                             return_value=None), \
                patch.object(self.application_module, '_auto_import_competitor_logos',
                             return_value=None), \
                patch.object(self.application_module, '_verify_competitor_rows',
                             return_value=None), \
                patch.object(self.application_module, '_verify_market_urls',
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

    def test_market_search_ran_counts_only_opened_pages(self):
        """A reply is "searched" when the Chromium workers actually opened
        pages (url_citation annotations) or provider-native grounding proves
        a real search ran (webSearchQueries) — not merely because the model
        produced JSON."""
        module = self.application_module
        memory = {'choices': [{'message': {'content': '{"competitors": []}'}}]}
        browsed = {'choices': [{'message': {
            'content': '{"competitors": []}',
            'annotations': [{'url_citation': {
                'url': 'https://rei.rega.gov.sa/ar', 'title': 'صفحة'}}],
        }}]}
        grounded = {'choices': [{'message': {
            'content': '{"competitors": []}',
            'annotations': [],
            'groundingMetadata': {'webSearchQueries': ['صفقات جدة']},
        }}]}
        self.assertFalse(module._market_search_ran(memory))
        self.assertTrue(module._market_search_ran(browsed))
        self.assertTrue(module._market_search_ran(grounded))

    def test_verify_row_marks_agent_failure_as_search_not_run(self):
        """A hard agent error — transport or launch — is an explicit
        search_not_run carrying the failure, never a fabricated-name verdict
        and never a silent paid fallback."""
        module = self.application_module
        row = {'name': 'مجمع الفرسان', 'row_source': 'ai', 'id': 'r1'}
        failed = {'error': {'message': 'browse_agent: launch_failed'}}
        with patch.object(module, '_browse_agent_call', return_value=dict(failed)):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'search_not_run')
        self.assertIn('launch_failed', row.get('verify_provider_error') or '')
        self.assertFalse(row.get('no_search_evidence'))

    def test_verify_row_rides_the_task_model(self):
        """Every verify run forwards MARKET_STUDY_MODEL — the same big mind —
        not a separate agent model."""
        import agent
        module = self.application_module
        seen = {}

        def fake_run(task, **kwargs):
            seen.update(kwargs)
            return {'choices': [{'message': {'content': '{"exists": false}'}}]}

        row = {'name': 'مجمع الفرسان', 'row_source': 'ai', 'id': 'r1'}
        with patch.object(agent, 'run_browse_agent', side_effect=fake_run):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(seen.get('model'), module.MARKET_STUDY_MODEL)
        self.assertEqual(row.get('verify_state'), 'search_not_run')

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
        with patch.object(module, '_browse_agent_call', return_value=response):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn('https://developer.example/listing-77', row.get('source_urls') or [])
        self.assertIn('450000', str(row.get('price_value') or ''))

    def test_verify_competitor_price_comes_from_opened_pages(self):
        """The agent's own loop keeps digging for the price — the orchestrator
        runs once and applies only a figure citing a page the browser opened."""
        module = self.application_module
        row = {'name': 'مجمع الفرسان', 'row_source': 'ai', 'id': 'r1'}
        priced = {
            'choices': [{'message': {
                'content': '{"exists": true, "price": {"value": "320000", '
                           '"url": "https://developer.example/fursan-prices"}}',
                'annotations': [{'url_citation': {
                    'url': 'https://developer.example/fursan-prices',
                    'title': 'أسعار مجمع الفرسان', 'content': ''}}],
            }}],
        }
        calls = []

        def fake_model(*_args, **_kwargs):
            calls.append(1)
            return priced

        with patch.object(module, '_browse_agent_call', side_effect=fake_model):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn('320000', str(row.get('price_value') or ''))
        self.assertEqual(len(calls), 1)

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
        }
        prompts = []

        def fake_model(*args, **_kwargs):
            prompts.append(args[1] if len(args) > 1 else '')
            return searched

        with patch.object(module, '_browse_agent_call', side_effect=fake_model):
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
        with patch.object(self.application_module, '_browse_agent_call',
                          return_value=grounded), \
                patch.object(self.application_module, '_run_market_source_plan',
                             return_value=None), \
                patch.object(self.application_module, '_new_evidence_pool',
                             return_value=None), \
                patch.object(self.application_module, '_auto_import_competitor_logos',
                             return_value=None), \
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
            return responses.pop(0) if responses else verify

        module = self.application_module
        with patch.object(module, '_browse_agent_call', side_effect=fake_model), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None), \
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
        failed = {'error': {'message': 'provider finished with MALFORMED_FUNCTION_CALL'}}
        with patch.object(self.application_module, '_browse_agent_call',
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
        gate = {'error': {'message': 'لا يوجد مفتاح AI مفعل لهذه الشركة',
                          'error_code': 'NO_TENANT_KEY'}}
        calls = []

        def fake_model(*_args, **_kwargs):
            calls.append(1)
            return grounded if not calls[1:] else dict(gate)

        module = self.application_module
        with patch.object(module, '_browse_agent_call', side_effect=fake_model), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_new_evidence_pool', return_value=None), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None), \
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
        # 1 main call + one agent run per row + the logo-discovery batch.
        self.assertLessEqual(len(calls), 10)

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
                'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة كل مدينة تحت مسار /ar/cities تعرض عدد صفقاتها وقيمتها والحي الأكثر نشاطًا؛ صفحات البحث المتقدم في المنصة تتطلب دخول نفاذ',
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
            4: ['منصة عقار aqar.fm', 'منصات المسوقين العقاريين المرخصين'],
            5: ['Google Maps للمواقع والمسافات والخدمات maps.google.com',
                'Google Places للتقييمات والحركة المحيطة',
                'المواقع الإخبارية الموثوقة', 'البيانات الصحفية الرسمية'],
        }
        self.assertEqual(market_study.SOURCE_PRIORITY, expected)
        expected_type_sources = {
            'سكني': [
                'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة المدينة تحت /ar/cities: عدد الصفقات وقيمتها والحي الأكثر نشاطًا',
                'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data',
                'الهيئة العامة للإحصاء stats.gov.sa',
                'البنك المركزي السعودي sama.gov.sa', 'وافي red.rega.gov.sa',
                'سكني sakani.sa وNHC nhc.sa', 'الأمانة وبلدي balady.gov.sa',
                'المواقع الرسمية للمطورين',
                'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
                'منصة عقار aqar.fm',
                'Google Maps للموقع والخدمات فقط',
            ],
            'تجاري': [
                'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة المدينة تحت /ar/cities — وشبكة إيجار ejar.sa',
                'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول الوحدات التجارية',
                'الهيئة العامة للإحصاء stats.gov.sa', 'وزارة التجارة mc.gov.sa',
                'الأمانة وبلدي balady.gov.sa', 'البنك المركزي السعودي sama.gov.sa',
                'المواقع الرسمية للمراكز والمشروعات التجارية',
                'تداول saudiexchange.sa وتقارير الصناديق العقارية',
                'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa وSavills savills.me',
                'منصة عقار aqar.fm',
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
        self.assertEqual(parsed['summary']['city_position'], '')
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
        self.assertIn('"title":"دراسة السوق"', market_study.build_summary_user_prompt({}, []))
        self.assertIn('دون حد للكلمات', market_study.build_summary_user_prompt({}, []))
        self.assertIn('احذف الفئات الفرعية غير المتاحة', market_study.build_summary_user_prompt({}, []))
        summary_prompt = market_study.build_summary_user_prompt({}, [])
        self.assertIn('الملخص والمصادر وSWOT السابقة للسياق فقط', summary_prompt)
        self.assertIn('المهام المحورية:', summary_prompt)
        self.assertIn('"market_definition":"تحليل تفصيلي"', summary_prompt)
        self.assertIn('فقرة تنفيذية متماسكة كاملة بلا حد للكلمات', summary_prompt)
