class MeetingRequirementsTestsPart04(MeetingRequirementsTests):

    def test_new_tables_are_created_on_an_existing_database(self):
        """_create_tables used to return early when `tenants` existed, so every table added after
        the first deploy was missing forever on existing installs, surfacing as a 500 from
        whichever endpoint touched it."""
        import sqlite3
        import tempfile

        source = read_module_source('db.py')
        self.assertNotIn("if cur and cur.fetchone():\n            return", source)

        path = os.path.join(tempfile.mkdtemp(), 'existing.db')
        original = db.DB_PATH
        try:
            db.DB_PATH = path
            db.init_db()
            conn = sqlite3.connect(path)
            conn.execute('DROP TABLE IF EXISTS tenant_team_entities')
            conn.commit()
            conn.close()

            db.init_db()  # what a deploy does
            conn = sqlite3.connect(path)
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn('tenant_team_entities', names,
                          'a missing table must be recreated on an existing database')
        finally:
            db.DB_PATH = original

    def test_project_team_section_scopes_choices_to_one_file(self):
        """A file may drop a library entity, override its role, or add an entity of its own —
        none of which may leak into other projects."""
        index_source = read_frontend_text()

        self.assertIn("div.dataset.section = 'section-team'", index_source)
        self.assertIn("createProjectSectionHeader('section-team', 'فريق العمل')", index_source)
        self.assertIn('data-key="team_selection"', index_source)

        # The project form keeps the requested order, with the timeline feeding the financial study and contact at the end.
        self.assertIn("const sectionOrder = ['basic', 'location', 'land_croquis'];", index_source)
        build_start = index_source.index('addTimelineTable(form);')
        build_end = index_source.index('const projectSections = Array.from', build_start)
        build_source = index_source[build_start:build_end]
        self.assertLess(build_source.index('addTimelineTable(form);'), build_source.index('addFinancialCalculations(form);'))
        self.assertLess(build_source.index('addFinancialCalculations(form);'), build_source.index('addTeamSection(form);'))
        self.assertLess(build_source.index('addTeamSection(form);'), build_source.index('addExecutiveContentSection(form)'))
        self.assertLess(build_source.index('addExecutiveContentSection(form)'), build_source.index("renderFormSection('contact')"))
        self.assertNotIn('addConceptualPlansSection(form)', build_source)

        # The three per-file behaviours.
        self.assertIn('function toggleTeamEntityInFile(entityId)', index_source)
        self.assertIn('function setProjectTeamRole(entityId, role)', index_source)
        self.assertIn('function addLocalTeamEntity()', index_source)
        self.assertIn('function removeLocalTeamEntity(localId)', index_source)
        # Project-only entities get the full field set, including a logo upload.
        self.assertIn('function updateLocalTeamEntity(localId, key, value)', index_source)
        self.assertIn('function uploadLocalTeamLogo(localId, input)', index_source)
        self.assertNotIn("prompt('اسم الجهة')", index_source)

        # The whole per-file choice set round-trips through the draft.
        client = self.app.test_client()
        selection = {
            'excluded': ['library-entity-1'],
            'roles': {'library-entity-2': 'المشرف على التنفيذ'},
            'local': [{'localId': 'local-1', 'categoryLabel': 'مقاول',
                       'name': 'شركة التنفيذ', 'role': 'المقاول الرئيسي'}],
        }
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'team_selection': json.dumps(selection, ensure_ascii=False)}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        restored = json.loads(draft_data['team_selection'])
        self.assertEqual(restored['excluded'], ['library-entity-1'])
        self.assertEqual(restored['roles']['library-entity-2'], 'المشرف على التنفيذ')
        self.assertEqual(restored['local'][0]['name'], 'شركة التنفيذ')

    def test_team_logos_must_be_images(self):
        client = self.app.test_client()
        rejected = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'team_logo',
            'file': (io.BytesIO(b'%PDF-1.4 not a logo'), 'logo.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(rejected.status_code, 400, rejected.get_json())
        self.assertIn('team_logo', self.application_module.PROJECT_FILE_TYPES)
        self.assertIn('team_logo', self.application_module.PROJECT_IMAGE_ONLY_TYPES)

    def test_competitor_logos_are_tenant_scoped_official_only_and_rendered_in_slides(self):
        client = self.app.test_client()
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        created = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'competitor_logo', 'draftId': 'draft-competitor-logo',
            'projectId': 'competitor-1', 'file': (io.BytesIO(png_bytes), 'logo.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(created.status_code, 201, created.get_json())
        file_id = created.get_json()['file']['id']
        with self.app.app_context():
            stored = db.get_project_file(self.tenant_a, file_id)
            self.assertEqual(stored['file_type'], 'competitor_logo')
            self.assertEqual(stored['draft_id'], 'draft-competitor-logo')
            self.assertEqual(stored['project_id'], 'competitor-1')
            self.assertIsNone(db.get_project_file(self.tenant_b, file_id))

        module = self.application_module
        self.assertFalse(module._safe_public_host('127.0.0.1'))
        with patch.object(module.requests, 'get') as request_get:
            _content, _mime, _extension, error = module._safe_download_competitor_logo(
                'https://cdn.example/logo.png', 'https://developer.example/project')
        request_get.assert_not_called()
        self.assertIn('خارج الموقع الرسمي', error)
        self.assertTrue(module._same_official_host(
            'https://cdn.developer.example/logo.png', 'https://project.developer.example/about'))
        self.assertFalse(module._same_official_host(
            'https://cdn.other.example/logo.png', 'https://project.developer.example/about'))
        pinned_pool = Mock()
        pinned_response = Mock()
        pinned_pool.urlopen.return_value = pinned_response
        with patch.object(module, 'HTTPSConnectionPool', return_value=pinned_pool) as pool_factory:
            returned_pool, returned_response = module._open_pinned_https(
                module.urlsplit('https://developer.example/assets/logo.png?v=1'), ('203.0.113.10',))
        self.assertIs(returned_pool, pinned_pool)
        self.assertIs(returned_response, pinned_response)
        self.assertEqual(pool_factory.call_args.args[0], '203.0.113.10')
        self.assertEqual(pool_factory.call_args.kwargs['assert_hostname'], 'developer.example')
        self.assertEqual(pool_factory.call_args.kwargs['server_hostname'], 'developer.example')
        self.assertEqual(pinned_pool.urlopen.call_args.args[:2], ('GET', '/assets/logo.png?v=1'))
        self.assertEqual(pinned_pool.urlopen.call_args.kwargs['headers']['Host'], 'developer.example')

        valid_response = Mock(status=200)
        valid_response.headers = {'Content-Type': 'image/png', 'Content-Length': str(len(png_bytes))}
        valid_response.stream.return_value = [png_bytes]
        pool = Mock()
        with patch.object(module, '_public_host_addresses', return_value=('203.0.113.10',)), \
                patch.object(module, '_open_pinned_https', return_value=(pool, valid_response)):
            content, mime_type, extension, error = module._safe_download_competitor_logo(
                'https://developer.example/logo.png', 'https://developer.example/project')
        self.assertEqual(content, png_bytes)
        self.assertEqual((mime_type, extension, error), ('image/png', '.png', ''))
        valid_response.release_conn.assert_called_once()
        pool.close.assert_called_once()

        creative = {'competitor_logos': [
            {'name': 'المنافس الأول', 'logo': '/uploads/creative/competitor-1.png'},
            {'name': 'المنافس الثاني', 'logo': '/uploads/creative/competitor-2.png'},
        ]}
        finished = module.slide_engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><h1>المنافسون</h1></div>',
            'content', {}, {'primary_color': '#123456'}, creative_images=creative,
            content_source='market_study_data.competitors', slide_num=3, total_slides=6,
        )
        self.assertIn('data-competitor-logos="1"', finished)
        self.assertIn('/uploads/creative/competitor-1.png', finished)
        self.assertIn('/uploads/creative/competitor-2.png', finished)
        self.assertNotIn('##COMPETITOR_LOGO_', finished)
        index_source = read_frontend_text()
        self.assertIn("formData.append('fileType', 'competitor_logo')", index_source)
        self.assertIn('data-field="logo_cell"', index_source)
        self.assertIn('logoImportWarning', index_source)
        # Logos import automatically inside the competitors job — no per-row button.
        self.assertNotIn('استيراد رسمي', index_source)
        self.assertNotIn('data-import-competitor-logo', index_source)
        app_source = read_module_source('app.py')
        self.assertIn('_auto_import_competitor_logos(', app_source)
        self.assertIn('def _auto_import_competitor_logos', app_source)
        self.assertIn('citation_pages=', app_source)

    def test_competitor_slide_renders_full_rows_logos_scope_and_horizontal_chart(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع تجريبي',
            'market_study_data': {
                'competitor_radius': '10',
                'data_period': '12m',
                'sources': [{'title': 'الموقع الرسمي', 'url': 'https://example.com/market'}],
                'competitors': [
                    {
                        'name': 'رافلز', 'project_type': 'فندقي', 'classification': 'مباشر',
                        'area_sqm': '1,200', 'status': 'قائم', 'operation_type': 'تشغيل فندقي',
                        'price_type': 'سعر الليلة', 'price_currency': 'SAR', 'price_value': '1548',
                        'source': 'الموقع الرسمي', 'source_urls': ['https://example.com/raffles'],
                        'notes': 'بيانات موثقة', 'logo_file_id': 'raffles-file',
                        'logo_path': '/uploads/raffles.png',
                    },
                    {
                        'name': 'سومو', 'project_type': 'سكني', 'classification': 'مرجعي',
                        'area_mode': 'range', 'area_from': '900', 'area_to': '1500',
                        'status': 'تحت الإنشاء', 'operation_type': 'بيع',
                        'price_type': 'نطاق سعري', 'price_from': '900000', 'price_to': '1200000',
                        'source': 'منصة موثقة', 'source_url': 'https://example.com/sumou',
                        'logo_file_id': 'sumou-file',
                    },
                ],
            },
        }
        slide = {
            'title': 'مقارنة المنافسين', 'type': 'content', 'section_key': 'market',
            'chart_type': 'horizontal_bar', 'content_source': 'market_study_data.competitors',
            'source_table': 'competitors',
        }
        raw = engine._build_sol_horizontal_bar_slide(
            slide, project, {'primary_color': '#123456', 'accent_color': '#c59a58'},
            slide_num=4, total_slides=8,
        )
        for value in ('data-competitor-table="1"', 'رافلز', 'سومو', 'فندقي', 'مباشر',
                      '1,200', 'تحت الإنشاء', 'تشغيل فندقي', '1,548', '900,000',
                      'https://example.com/raffles', 'المصدر 1', 'نطاق المنافسين',
                      '##COMPETITOR_LOGO_1##', '##COMPETITOR_LOGO_2##', 'width:100%'):
            self.assertIn(value, raw)
        # The sources column carries numbered links only — no notes prose.
        self.assertNotIn('بيانات موثقة', raw)
        self.assertGreaterEqual(raw.count('<tr'), 3)

        finished = engine.finalize_slide_html(
            raw, 'content', project, {'primary_color': '#123456'},
            creative_images={'competitor_logos': [
                {'name': 'رافلز', 'logo': '/uploads/raffles.png'},
                {'name': 'سومو', 'logo': '/uploads/sumou.png'},
            ]},
            content_source='market_study_data.competitors', slide_num=4, total_slides=8,
        )
        self.assertIn('/uploads/raffles.png', finished)
        self.assertIn('/uploads/sumou.png', finished)
        self.assertNotIn('##COMPETITOR_LOGO_', finished)
        self.assertNotIn('src=""', finished)

        renumbered = engine.renumber_presentation_slides([
            {**slide, 'html': finished},
        ], branding={'primary_color': '#123456'}, project_data=project)
        self.assertIn('/uploads/raffles.png', renumbered[0]['html'])
        self.assertIn('/uploads/sumou.png', renumbered[0]['html'])

        note = engine._slide_source_data_note(slide, project)
        for value in ('classification', 'area_sqm', 'operation_type', 'price_value', 'الموقع الرسمي', 'رافلز', 'نطاق وفترة البيانات'):
            self.assertIn(value, note)

    def test_competitor_slide_is_planned_when_named_rows_have_no_canonical_price_key(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع بلا سعر',
            'market_study_data': {'competitors': [{'name': 'منافس محفوظ', 'price': {'value': '1750'}}]},
        }
        plan = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, project, {})
        comp_slide = next((slide for slide in plan['slides']
                           if slide.get('content_source') == 'market_study_data.competitors'), None)
        self.assertIsNotNone(comp_slide)
        self.assertEqual(comp_slide.get('chart_type'), 'horizontal_bar')

    def test_competitor_finalization_restores_the_fixed_table_when_ai_returns_chart_only(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع مقارنة',
            'market_study_data': {
                'competitors': [{
                    'name': 'منافس محفوظ', 'price_value': '1750',
                    'price_type': 'سعر الليلة', 'operation_type': 'بيع',
                }],
            },
        }
        chart_only = '<div class="slide" style="width:1280px;height:720px"><div>الرسم فقط</div></div>'
        finished = engine.finalize_slide_html(
            chart_only, 'content', project, {'primary_color': '#123456'},
            creative_images=[], slide_num=3, slide_title='مقارنة المنافسين',
            total_slides=8, content_source='market_study_data.competitors',
        )
        self.assertIn('data-competitor-table="1"', finished)
        self.assertIn('منافس محفوظ', finished)
        self.assertIn('مقارنة أسعار المنافسين في السوق', finished)
        self.assertIn('1,750', finished)
        self.assertNotIn('data-market-auto-fit="1"', finished)

    def test_market_sol_design_is_free_and_postprocess_centers_its_content(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع سوق',
            'market_study_data': {
                'one_block_summary': 'ملخص سوقي موثق ومتكامل.'
            },
        }
        slide = {
            'title': 'ملخص دراسة سوق العمل', 'type': 'content',
            'section_key': 'market', 'design_style': 'text',
            'content_source': 'market_study_data.one_block_summary',
        }
        prompt = engine.build_slide_user_msg(
            slide, 4, 9, {'primary_color': '#123456'}, project_data=project,
        )
        self.assertIn('لا تفرض جدولاً أو بطاقات أو شبكة بعينها', prompt)
        self.assertIn('لا تكرر قالباً واحداً بين الشرائح', prompt)
        self.assertIn('لا تستخدم وسم <table>', prompt)
        self.assertNotIn('للملخص التنفيذي: قسّم الفقرة المعتمدة بصرياً', prompt)
        raw = (
            '<div class="slide" style="width:1280px;height:720px;position:relative;">'
            '<style>.slide{color:#111}</style>'
            '<header data-slide-header="1">العنوان</header>'
            '<div style="height:320px">'
            '<div style="position:absolute!important;top:120px;left:20px;height:180px;">المحتوى</div>'
            '<div style="position: fixed; right:20px; bottom:80px; height:90px;">نص إضافي</div>'
            '</div>'
            '<footer data-slide-footer="1">التذييل</footer>'
            '</div>'
        )
        normalized = engine._normalize_market_content_layout(
            raw, slide_type='content', slide_title=slide['title'],
            content_source=slide['content_source'],
        )
        self.assertIn('data-market-auto-fit="1"', normalized)
        self.assertIn('data-market-auto-fit-content="1"', normalized)
        self.assertIn('justify-content:safe center', normalized)
        self.assertIsNone(re.search(
            r'<[^>]+\bstyle\s*=\s*["\'][^"\']*position\s*:\s*(?:absolute|fixed)',
            normalized, flags=re.IGNORECASE,
        ))
        self.assertIn('position:relative!important', normalized)
        self.assertEqual(engine._validate_market_visual_design('<div>نص</div>', slide), None)
        finished = engine.finalize_slide_html(
            raw, 'content', project,
            {'primary_color': '#123456', 'logo_path': '/tenant-assets/demo/logo'},
            tenant_id='tenant-a', slide_num=4, slide_title=slide['title'],
            total_slides=9, content_source=slide['content_source'],
        )
        self.assertIn('class="presentation-chrome-logo"', finished)
        self.assertIn('/tenant-assets/demo/logo?t=1', finished)
        self.assertIn('padding:0!important', finished)

    def test_only_competitor_market_page_uses_fixed_renderer(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع سوق حر',
            'market_study_data': {
                'one_block_summary': 'ملخص سوقي حر يختاره SOL بصريًا دون قالب مسبق.'
            },
        }
        slide = {
            'title': 'ملخص دراسة سوق العمل', 'type': 'content',
            'section_key': 'market', 'design_style': 'text',
            'chart_type': 'horizontal_bar',
            'content_source': 'market_study_data.one_block_summary',
        }
        calls = []

        def call_glm(*args, **kwargs):
            calls.append((args, kwargs))
            return {'choices': [{'message': {'content': (
                '<div class="slide" style="width:1280px;height:720px;">'
                '<div data-sol-owned="1">ملخص سوقي حر يختاره SOL بصريًا دون قالب مسبق.</div>'
                '</div>'
            )}}]}

        result = engine.generate_single_slide(
            'system', slide, 6, 10, {'primary_color': '#123456'},
            call_glm, max_retries=0, project_data=project,
        )
        self.assertEqual(len(calls), 1)
        self.assertIn('data-sol-owned="1"', result)
        self.assertNotIn('data-competitor-table', result)
        self.assertIn('data-slide-header="1"', result)

    def test_free_market_retries_preserve_sol_composition_instead_of_template(self):
        engine = self.application_module.slide_engine
        project = {
            'project_name': 'مشروع سوق حر',
            'market_study_data': {
                'one_block_summary': 'النص المعتمد الكامل الذي يجب عرضه داخل الشريحة.'
            },
        }
        slide = {
            'title': 'ملخص دراسة سوق العمل', 'type': 'content',
            'section_key': 'market', 'content_source': 'market_study_data.one_block_summary',
        }

        def call_glm(*args, **kwargs):
            return {'choices': [{'message': {'content': (
                '<div class="slide" style="width:1280px;height:720px;">'
                '<section data-sol-editorial="1">تكوين حر من SOL لم ينسخ النص المعتمد حرفياً.</section>'
                '</div>'
            )}}]}

        result = engine.generate_single_slide(
            'system', slide, 6, 10, {'primary_color': '#123456'},
            call_glm, max_retries=0, project_data=project,
        )
        self.assertIn('data-sol-editorial="1"', result)
        self.assertNotIn('data-market-work-summary', result)

    def test_competitor_logo_import_discovers_a_cited_official_site_and_preserves_manual_files(self):
        module = self.application_module
        client = self.app.test_client()
        official_url = 'https://project.example.com/about'
        logo_url = 'https://cdn.example.com/project-logo.png'
        response = {'choices': [{'message': {
            'content': json.dumps({
                'official_url': official_url,
                'logo_url': logo_url,
                'logo_source_url': official_url,
            }),
            'annotations': [{'url_citation': {'url': official_url}}],
        }}]}

        def store_logo(row, draft_id=None):
            result = dict(row)
            result['logo_file_id'] = 'imported-logo-file'
            result['logo_path'] = '/uploads/creative/imported-logo.png'
            return result

        with patch.object(module, '_call_market_study_model', return_value=(response, '')) as model_call, \
                patch.object(module, '_store_imported_competitor_logo', side_effect=store_logo):
            imported = client.post('/api/market-study/competitors/logo', headers=self._headers(self.token_a), json={
                'draftId': 'logo-discovery-draft',
                'competitor': {'id': 'arabic-project', 'name': 'مشروع عربي', 'source': 'منصة عقار'},
            })
        self.assertEqual(imported.status_code, 200, imported.get_json())
        competitor = imported.get_json()['competitor']
        self.assertEqual(competitor['logo_file_id'], 'imported-logo-file')
        self.assertEqual(competitor['logo_source_url'], official_url)
        self.assertEqual(competitor['field_sources']['logo_url'], [official_url])
        self.assertIn(official_url, competitor['source_urls'])
        self.assertTrue(competitor['logo_official_verified'])
        self.assertEqual(model_call.call_count, 1)

        with patch.object(module, '_call_market_study_model') as model_call:
            preserved = client.post('/api/market-study/competitors/logo', headers=self._headers(self.token_a), json={
                'competitor': {
                    'id': 'manual-logo-project', 'name': 'مشروع يدوي',
                    'logo_file_id': 'manual-file', 'logo_path': '/uploads/creative/manual.png',
                },
            })
        self.assertEqual(preserved.status_code, 200, preserved.get_json())
        self.assertEqual(preserved.get_json()['competitor']['logo_file_id'], 'manual-file')
        model_call.assert_not_called()

    def test_drafts_are_saved_only_on_request(self):
        """Edits stay local until the explicit save action is requested."""
        index_source = read_frontend_text()

        self.assertNotIn('draftAutoSaveTimer', index_source)
        self.assertNotIn('[DRAFT AUTOSAVE]', index_source)
        self.assertIn('function triggerAutoSaveDraft() {\n      setDraftDirty(true);\n    }', index_source)
        self.assertIn('function setDraftDirty(dirty)', index_source)
        self.assertIn('تغييرات غير محفوظة', index_source)

        # Losing unsaved work silently is worse than a prompt.
        self.assertIn("window.addEventListener('beforeunload'", index_source)
        self.assertIn('if (!tenantDraftDirty) return;', index_source)

        # A successful save clears the flag.
        self.assertIn('tenantDraftDirty = false;', index_source)

        # Deleting a draft addressed a route that does not exist, so it silently failed.
        self.assertNotIn("api('DELETE', '/api/project-draft');", index_source)
        self.assertIn("api('DELETE', '/api/project-draft/' + encodeURIComponent(draftId))", index_source)
        app_source = read_module_source('app.py')
        self.assertNotIn("@app.route('/api/project-draft', methods=['DELETE'])", app_source)

    def test_project_form_action_bar_stays_visible_while_scrolling_every_section(self):
        """Save/back stay on screen while the user is inside a long section, then settle at the
        natural page end. The bar is shared by every project-form section, including floor design."""
        index_source = read_frontend_text()
        self.assertIn('.tenant-form-actions {', index_source)
        actions_start = index_source.index('.tenant-form-actions {')
        actions_end = index_source.index('}', actions_start)
        actions_css = index_source[actions_start:actions_end]
        self.assertIn('position: sticky', actions_css)
        self.assertIn('bottom: 10px', actions_css)
        self.assertNotIn('#tenantProjectPage.tenant-floor-design-project-mode>.tenant-form-actions', index_source)
        self.assertIn('<div class="tenant-form-actions">', index_source)
        self.assertIn('onclick="saveProjectAsDraft()"', index_source)

    def test_deep_links_serve_the_spa_instead_of_a_404(self):
        """Reloading or sharing a client-side route must not drop the user on an error page."""
        client = self.app.test_client()
        html_headers = {'Accept': 'text/html'}
        for path in ('/', '/app', '/app/dashboard', '/app/projects/new',
                     '/app/projects/visual-concept',
                     '/app/settings/users', '/projects/123/financial',
                     '/superadmin', '/superadmin/admin',
                     '/c/acme/dashboard', '/c/acme/presentations/current'):
            response = client.get(path, headers=html_headers)
            self.assertEqual(response.status_code, 200, f'{path} should serve the SPA shell')

        # Reserved prefixes must keep real 404s rather than returning HTML.
        for path in ('/api/does-not-exist', '/uploads/missing.png', '/assets/missing.js'):
            self.assertEqual(client.get(path, headers=html_headers).status_code, 404, path)
        # Non-GET and non-HTML requests must not be answered with the shell either.
        self.assertEqual(client.post('/definitely-not-a-route').status_code, 404)
        self.assertEqual(client.get('/definitely-not-a-route').status_code, 404)

    def test_role_prefixed_routes_resolve_to_a_stable_latin_slug(self):
        """Super-admin lives under /superadmin, each company under /c/<slug>.

        The slug is the stable latin subdomain/username, never the Arabic company
        name or a user name, and /app/* stays as a legacy alias."""
        self.assertEqual(db.tenant_slug({'id': 'abc', 'subdomain': 'Acme-Co', 'username': None}), 'acme-co')
        self.assertEqual(db.tenant_slug({'id': 'abc', 'subdomain': None, 'username': 'acme-user'}), 'acme-user')
        self.assertEqual(db.tenant_slug({'id': 'abc', 'subdomain': None, 'username': 'Acme_User'}), 'acme-user')
        fallback = db.tenant_slug({'id': 'ABCDEF12-3456', 'subdomain': None, 'username': None})
        self.assertTrue(fallback.startswith('t-'))
        self.assertNotIn(' ', fallback)
        index_source = read_frontend_text()
        for token in ('TENANT_ROUTE_SUFFIXES', 'tenantPathPrefix', 'tenantCanonicalRoute',
                      'resolveTenantRoutePath', 'enforceTenantRouteGuard',
                      'canonicalizeTenantUrl', '/superadmin', "'/c/' + slug"):
            self.assertIn(token, index_source)
        app_source = read_module_source('app.py')
        self.assertIn("'/superadmin", app_source)
        self.assertIn("'/c/<slug>'", app_source)

    def test_back_navigation_never_leaves_the_app(self):
        """"/" and unmapped paths fell through popstate, so the view and the URL disagreed and the
        next Back exited the site."""
        index_source = read_frontend_text()
        self.assertNotIn(
            "else if (tenantToken && window.location.pathname.startsWith('/app/')) showTenantPage('tenantDashboardPage', true);",
            index_source)
        self.assertIn("showTenantPage('tenantDashboardPage', true);\n      syncTenantBrowserHistory('tenantDashboardPage', {}, true);",
                      index_source)
        # A requested path wins over the remembered page, and "/" is rewritten to a real route.
        # Role-prefixed URLs resolve through resolveTenantRoutePath first, with the legacy
        # /app map kept as fallback so old bookmarks still land on the requested page.
        self.assertIn('resolveTenantRoutePath(window.location.pathname)', index_source)
        self.assertIn('TENANT_ROUTE_PAGES[window.location.pathname]', index_source)
        self.assertIn("if (window.location.pathname === '/') {", index_source)
        self.assertIn('if (current && TENANT_PAGE_ROUTES[current]) syncTenantBrowserHistory(current, {}, true);',
                      index_source)

    def test_project_refresh_reopens_the_saved_draft(self):
        """Refreshing the project form must reopen the remembered draft, not a blank project."""
        index_source = read_frontend_text()
        self.assertIn('const savedDraftId = navigation && navigation.draftId &&', index_source)
        self.assertIn('if (!(savedDraftId && await openProjectDraftById(savedDraftId)))', index_source)
        self.assertIn('await startTenantProject()', index_source)

    def test_timeline_is_the_only_source_of_dev_duration_and_stages(self):
        """The financial study mirrors the timeline read-only so the two cannot disagree."""
        index_source = read_frontend_text()

        self.assertIn('function syncFinancialFromTimeline()', index_source)

        # Development duration is taken from the timeline's year count and is not editable here.
        self.assertIn('id="developmentYears" type="number" min="1" value="" readonly', index_source)
        self.assertNotIn('id="developmentYears" type="number" min="1" value="4" oninput', index_source)
        self.assertIn("مأخوذة من «عدد السنوات» في قسم الجدول الزمني", index_source)

        # The year count mirrors on its own: gating it on the stage list left «مدة تطوير المشروع»
        # showing 4 while the timeline said 5, in a box the user cannot edit.
        self.assertNotIn('if (namedStages.length && devYearsInput', index_source)
        self.assertIn("const nextDevYears = Number.isFinite(timelineYears) && timelineYears > 0 ? String(timelineYears) : '';",
                      index_source)
        self.assertIn('if (devYearsChanged) recalculate();', index_source)

    def test_mirrored_financial_inputs_never_show_a_figure_their_source_lacks(self):
        """These four boxes are read-only and say they come from another section, so a value the
        source does not have is invented data the user cannot correct. The study used to open on
        70,000 م², 35% تغطية, دور واحد and 4 سنوات that nobody entered, and clearing a source left
        the previous number behind because the mirror only wrote when the source was non-zero."""
        index_source = read_frontend_text()
        for element in ('id="landArea" type="number" value=""',
                        'id="coverageRate" type="number" value=""',
                        'id="floorCount" type="number" min="1" value=""',
                        'id="developmentYears" type="number" min="1" value=""'):
            self.assertIn(element + ' readonly class="readonly-highlight"', index_source)
        self.assertNotIn('id="landArea" type="number" value="70000"', index_source)
        self.assertNotIn('id="coverageRate" type="number" value="35"', index_source)

        # An empty source clears the mirror instead of leaving the last value.
        self.assertIn("const next = raw !== '' && number > 0 ? String(number) : '';", index_source)
        self.assertIn("mirrorApproved(landAreaInput, 'approved_financial_area');", index_source)
        self.assertIn("mirrorApproved(floorInput, 'approved_floor_count');", index_source)
        self.assertIn("mirrorApproved(coverageInput, 'approved_coverage_ratio');", index_source)
        self.assertNotIn('if (landAreaInput && area > 0) landAreaInput.value', index_source)

        # Stage name and year are locked; only the two percentages remain editable.
        self.assertIn('<td data-field="name"><input value="${escapeHtml(d.name || \'\')}" readonly', index_source)
        self.assertIn('tr.dataset.stageYear = String(d.year ?? 1)', index_source)
        self.assertIn("tr.querySelectorAll('input:not([readonly])')", index_source)

        # No way to add or delete a stage from the financial study.
        self.assertNotIn('onclick="addScheduleStage()"', index_source)
        self.assertIn('المراحل وسنواتها تُعدّل من قسم الجدول الزمني', index_source)

        # The financial study seeds no stages of its own; the timeline drives the list (and owns
        # the editable default phases new projects open with).
        fin_start = index_source.index('function addFinancialCalculations(form)')
        fin_body = index_source[fin_start:index_source.index('function addComponent(', fin_start)]
        self.assertNotIn('addScheduleStage({', fin_body)
        self.assertNotIn('التصميم والتراخيص والأعمال المبكرة', fin_body)

        # Timeline rows already carry project-relative years — the same axis the cashflow uses —
        # and the percentages survive a rebuild.
        self.assertIn('const relative = parseInt(row.year, 10);', index_source)
        self.assertIn('previous.get(name) || {}', index_source)
        self.assertIn('tr.dataset.stageEndYear = String(d.endYear ?? d.year ?? 1)', index_source)
        self.assertIn('year >= r.year && year <= r.endYear', index_source)
        self.assertIn('developerPayment += devPctTotal ? developerCost * (r.devPct / devPctTotal) / span : 0', index_source)

        # Empty timeline warns rather than silently zeroing the cost distribution.
        self.assertIn('id="timelineStagesWarning"', index_source)
        self.assertIn('warning.hidden = namedStages.length > 0', index_source)
        # The stage list still guards the schedule rebuild — but not the year count, which is the
        # timeline's own field and mirrors on its own.
        self.assertIn('if (!namedStages.length) {\n        if (devYearsChanged) recalculate();\n        return;\n      }',
                      index_source)

        # The stage table lost its actions column, so the report must stop dropping the last one.
        self.assertIn("reportTableSnapshot('scheduleTable', false)", index_source)

        # Sidebar order comes from append order: the timeline feeds the financial study, so it
        # must be filled first and therefore listed first.
        timeline_at = index_source.index('addTimelineTable(form);')
        financial_at = index_source.index('addFinancialCalculations(form);')
        self.assertLess(timeline_at, financial_at,
                        'the timeline section must be appended before the financial study')

    def test_financial_study_mirrors_approved_build_inputs_from_land(self):
        """Approved area, floor count and coverage are owned by land/croquis and read-only here."""
        index_source = read_frontend_text()

        self.assertIn('function syncFinancialFromLand()', index_source)

        # The three approved-build fields come from the land/croquis section and are locked. They
        # start empty: a read-only box must never show a figure its source does not have.
        self.assertIn('id="landArea" type="number" value="" readonly', index_source)
        self.assertIn('id="coverageRate" type="number" value="" readonly', index_source)
        self.assertIn('id="floorCount" type="number" min="1" value="" readonly', index_source)
        self.assertIn('مأخوذة من «المساحة المعتمدة للدراسة المالية» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «التغطية المعتمدة» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «الأدوار المعتمدة» في قسم الأرض والكروكي', index_source)

        # Changing those land fields re-mirrors them into the financial study.
        self.assertIn(
            "f.fieldKey === 'approved_financial_area' || f.fieldKey === 'approved_floor_count' || f.fieldKey === 'approved_coverage_ratio'",
            index_source)
        self.assertIn("mirrorApproved(coverageInput, 'approved_coverage_ratio');", index_source)
        self.assertIn('const raw = readLand(key);', index_source)
        self.assertNotIn('parseCoverageFromLandText', index_source)

    def test_timeline_start_is_a_month_year_and_years_start_blank(self):
        """«سنة البداية» became «تاريخ البداية» (month+year), «عدد السنوات» opens empty, and the
        project end lands on the same month — 2/2030 + 5 years is 2/2035, not 3/2035."""
        index_source = read_frontend_text()

        # Month+year picker instead of the bare year input.
        self.assertIn('id="tlStartDate" data-key="timeline_start_date"', index_source)
        self.assertIn('type="month" id="tlStartDate"', index_source)
        self.assertNotIn('id="tlStartYear"', index_source)

        # «عدد السنوات» carries no invented default.
        self.assertIn('id="tlYears" data-key="timeline_years" data-type="number" min="1" value=""', index_source)

        # The end date is read-only and lands on the same month: start.index + years * 12.
        self.assertIn('id="tlEndDate" readonly', index_source)
        self.assertIn('formatTimelineMonth(start.index + years * 12)', index_source)

        # Quarters belong to the project year, which starts at the start month.
        self.assertIn('start.index + (year - 1) * 12 + quarterIndex * 3', index_source)

        # Drafts saved before «تاريخ البداية» carried a bare start year; hydration maps it to
        # January and rewrites calendar-year rows as project-relative years.
        self.assertIn("tenantProjectData.timeline_start_date = legacyStartYear + '-01';", index_source)
        self.assertIn('calendarYear - legacyStartYear + 1', index_source)

    def test_new_projects_seed_the_standard_phases_as_editable_rows(self):
        """Every new project opens with the five standard phases named — a starting point the
        client edits freely; drafts hydrate their own rows and never get the defaults."""
        index_source = read_frontend_text()

        self.assertIn('const TIMELINE_DEFAULT_PHASES = [', index_source)
        for phase in ('التصميم، الدراسات، التراخيص',
                      'تجهيز الموقع والأساسات والهيكل الإنشائي',
                      'استكمال الهيكل وأعمال الكهرباء والميكانيكا',
                      'التشطيبات والأعمال الخارجية',
                      'الاختبارات والتسليم والتسويق'):
            self.assertIn(phase, index_source)
        # Seeding happens on the new-project path only, after the form is built.
        start_fn = index_source.index('async function startTenantProject()')
        self.assertIn('seedDefaultTimelinePhases()', index_source[start_fn:start_fn + 4000])
        # The seed carries a name only — no invented year, quarter or duration.
        self.assertIn('TIMELINE_DEFAULT_PHASES.forEach(name => addTimelineRow({ name }));', index_source)
        # Seeded rows stay ordinary editable rows with a delete button.
        self.assertIn('function seedDefaultTimelinePhases()', index_source)
        self.assertIn('function removeTimelineRow(button)', index_source)

    def test_timeline_starts_blank_with_a_quarter_picker_and_row_delete(self):
        """Phases are client data, so the table must not seed invented stages."""
        index_source = read_frontend_text()

        # The seeding table and its quarter-advancing loop are gone. (The unrelated `timeline`
        # sample *text* field may still mention phase names; only the table must not seed rows.)
        self.assertNotIn("{ name: 'الحصول على التراخيص', q: 'Q1', dur: 3 }", index_source)
        self.assertNotIn('currentQ += Math.ceil', index_source)
        self.assertNotIn("value=\"Q${currentQ}\"", index_source)

        # The quarter is a picker, not a free-text box.
        self.assertIn("const TIMELINE_QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4'];", index_source)
        self.assertIn('<select class="tl-quarter"', index_source)
        self.assertNotIn('class="tl-quarter" value=', index_source)
        self.assertIn('function computeTimelineEnd(year, quarter, duration)', index_source)
        self.assertIn('class="tl-end"', index_source)
        self.assertIn('endYear: end ? String(end.year) : \'\'', index_source)
        # The owner asked for no how-to copy on screen; the notes column still feeds the slide.
        self.assertNotIn('الملاحظات تظهر مع المرحلة في شريحة الجدول الزمني', index_source)
        self.assertNotIn('الملاحظات داخلية في الملف فقط', index_source)
        self.assertIn('<th>إلى</th><th>الملاحظات</th>', index_source)

        # Rows can be deleted, and one editable row always survives.
        self.assertIn('function removeTimelineRow(button)', index_source)
        self.assertIn('onclick="removeTimelineRow(this)"', index_source)
        self.assertIn('if (!tbody.rows.length) addTimelineRow();', index_source)

        # The slide title/subtitle fields are gone: nothing consumed them, so they invited the user
        # to fill in a heading that reached neither the slides nor the PDF.
        self.assertNotIn('timeline_slide_title', index_source)
        self.assertNotIn('timeline_slide_subtitle', index_source)

        # A missing start date keeps the rows usable as relative years/quarters, with a warning.
        self.assertIn('id="timelineStartYearWarning"', index_source)
        self.assertIn('startYearWarning.hidden = !!projectStart || !namedStages.length;',
                      index_source)

        # A single shared builder feeds the blank row, the add button and draft hydration.
        self.assertIn('function timelineRowHtml(data = {})', index_source)
        self.assertIn('timelineRows.forEach(row => addTimelineRow(row));', index_source)

        # Saved phases still round-trip through the draft.
        client = self.app.test_client()
        rows = [{'name': 'التراخيص', 'year': '1', 'quarter': 'Q3',
                 'duration': '5', 'notes': 'بانتظار الأمانة'}]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'timeline_start_date': '2030-02',
                'timeline_years': '5',
                'timeline_table_data': json.dumps(rows, ensure_ascii=False),
            }
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        self.assertEqual(draft_data['timeline_start_date'], '2030-02')
        self.assertEqual(draft_data['timeline_years'], '5')
        restored = json.loads(draft_data['timeline_table_data'])[0]
        self.assertEqual(restored['quarter'], 'Q3')
        self.assertEqual(restored['notes'], 'بانتظار الأمانة')

        # With a 2/2030 start, year-1 quarter-3 covers months 7–9 of the project → 8–10/2030,
        # and a 5-month phase ends 12/2030 — real months on the slide, not bare year numbers.
        note = self.application_module.slide_engine._timeline_data_note({
            'timeline_start_date': '2030-02',
            'timeline_table_data': json.dumps(rows, ensure_ascii=False)
        })
        self.assertIn('التراخيص', note)
        self.assertIn('بانتظار الأمانة', note)
        self.assertIn('8/2030 إلى 12/2030', note)
        self.assertIn('إذا كانت الملاحظة فارغة فلا تعرض', note)
        empty_note_line = self.application_module.slide_engine.format_timeline_phase_line({
            'name': 'التصميم', 'year': '1', 'quarter': 'Q1',
            'endYear': '1', 'endQuarter': 'Q2', 'duration': '3', 'notes': '',
        })
        self.assertNotIn(' — ', empty_note_line)

        # A pre-migration draft (bare start year + calendar-year rows) is read on the relative
        # axis and still gets real month labels: start year 2026 maps to January, so the
        # calendar row 2027/Q1 becomes year 2 quarter 1 → Jan–Mar 2027.
        legacy_note = self.application_module.slide_engine._timeline_data_note({
            'timeline_start_year': '2026',
            'timeline_table_data': json.dumps(
                [{'name': 'التنفيذ', 'year': '2027', 'quarter': 'Q1', 'duration': '3'}],
                ensure_ascii=False)
        })
        self.assertIn('التنفيذ', legacy_note)
        self.assertIn('1/2027 إلى 3/2027', legacy_note)

    def test_components_live_only_inside_the_financial_study(self):
        """The standalone components section duplicated id="componentsTable", and duplicate ids
        make querySelector return only the first — so the financial readers were bound to the
        wizard table and its mismatched columns."""
        index_source = read_frontend_text()

        # Exactly one element may own the id.
        self.assertEqual(len(re.findall(r'id="componentsTable"', index_source)), 1)

        # The standalone section and its helpers are gone.
        for gone in ('addComponentsTable', 'addComponentRow', 'recalcComponents',
                     'componentsTableBody', 'components_table_data', 'section-components'):
            self.assertNotIn(gone, index_source, f'{gone} should have been removed')

        # The financial study still owns the richer table and its readers.
        self.assertIn('<table id="componentsTable">', index_source)
        self.assertIn('function addComponent(d = {})', index_source)
        self.assertIn('function getComponentRowsData()', index_source)
        self.assertIn('function validateComponentAreas()', index_source)
        self.assertIn("data-field=\"investmentModel\"", index_source)

        # Renamed section.
        self.assertIn("createProjectSectionHeader('section-financial-calc', 'الدراسة المالية والمؤشرات')",
                      index_source)
        self.assertIn('onclick="saveProjectAsDraft()">حفظ كمسودة</button>', index_source)
        self.assertIn('function applySectionLockState(sectionKey, status)', index_source)
        self.assertIn("toggleButton.textContent = status === 'approved' ? 'الغاء الاعتماد' : 'اعتماد';", index_source)
        self.assertNotIn("resetButton.textContent = 'إلغاء الاعتماد';", index_source)
        self.assertIn('function updateVisualConceptHomeCards()', index_source)
        self.assertIn('id="visualConceptHomeCoverPreview"', index_source)
        self.assertNotIn('الدراسة المالية المبسطة', index_source)

        # The backend still reports on the financial components table.
        app_source = read_module_source('app.py')
        self.assertIn("('3', 'مكونات المشروع', 'componentsTable')", app_source)

    def test_financial_validation_requires_only_enabled_optional_inputs(self):
        errors = self.application_module.validate_financial_model({
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'no', 'fundEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {},
        })
        self.assertEqual(errors, [])
        errors = self.application_module.validate_financial_model({
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'yes', 'fundEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {},
        })
        self.assertTrue(any(item['field'] == 'annualFinanceRate' for item in errors))
        self.assertTrue(any(item['field'] == 'financeDrawTable' for item in errors))

    def test_financial_export_uses_server_validator_and_skips_disabled_sections(self):
        model = {
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'no', 'fundEnabled': 'no',
                'fundFeesEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {
                'sensitivityAssumptionsTable': [{'key': 'executionCost', 'low': 90, 'high': 110, 'ترتيب / حذف': 'أعلى'}],
                'sensitivityTable': [{'scenario': 'أساسي', 'roi': '12%'}],
                'cashflowTable': [{'year': 1, 'final': -10, 'cumulative': -10}],
            },
            'projection': {'projectCost': 10},
            'dynamicRows': {'sensitivity': [{'key': 'executionCost', 'low': 90, 'high': 110}]},
        }
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
        self.assertNotIn('8. التمويل', html)
        self.assertNotIn('9. الصندوق وأتعابه', html)
        self.assertIn('12. النتائج المالية', html)
        self.assertIn('13. التدفقات النقدية السنوية', html)
        self.assertIn('14. تحليل الحساسية العام', html)
        self.assertIn('wide-table', html)
        self.assertIn('1,000', html)
        self.assertIn('90', html)
        self.assertIn('12%', html)
        self.assertNotIn('ترتيب / حذف', html)
        index_source = read_frontend_text()
        self.assertIn('function persistFinancialStudyDraftState()', index_source)
        self.assertIn("data-key=\"financial_study_model\"", index_source)
        self.assertIn('sensitivity: collectSensitivityVariables()', index_source)
        self.assertIn("existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')]", index_source)
        self.assertIn('if (source !== \'manual\') updateAutoQtyPreview(tr);', index_source)
        # Comma-formatted snapshot values used to be written back into type=number inputs,
        # which blank them, so the finance base and every derived field stayed at zero.
        self.assertIn("cleaned = cleaned.replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)));", index_source)
        self.assertIn('function financialInputNumber(value, fallback = 0)', index_source)
        self.assertIn('if (isFinancialNumericControl(input)) {', index_source)
        self.assertIn('inputs[el.id] = isFinancialNumericControl(el) ? parseNumber(el.value) : (el.value ?? \'\');', index_source)
        self.assertIn('value="${financialInputNumber(d.qty, 0)}"', index_source)
        client = self.app.test_client()
        with patch.object(self.application_module, 'generate_financial_pdf') as generate_pdf:
            response = client.post('/api/financial-study/export', headers=self._headers(self.token_a), json={
                'projectName': 'مشروع مالي', 'financialModel': model
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        generate_pdf.assert_called_once()
        export_source = read_module_source('app.py')
        export_at = export_source.index('def api_export_financial_study()')
        self.assertIn('@require_auth', export_source[export_at - 80:export_at])
        self.assertNotIn('@require_permission(\'export_files\')', export_source[export_at - 80:export_at])
        self.assertIn("Playwright failed ({error}); falling back to PyMuPDF", export_source)
        self.assertIn("str(error).strip() or type(error).__name__", export_source)
        self.assertIn('def _financial_pdf_plain_html(html):', export_source)
        self.assertIn('def generate_financial_pdf_from_model(project_name, model, output_path):', export_source)
        self.assertIn("generate_financial_pdf(report_html, output_path, model=model, project_name=project_name)", export_source)
        maps_source = read_module_source('maps_service.py')
        self.assertIn('def bundled_arabic_font_path():', maps_source)
        self.assertIn("os.path.join(FONTS_DIR, 'arabic-text.bin')", maps_source)
        font_path = ROOT / 'fonts' / 'arabic-text.bin'
        self.assertGreater(font_path.stat().st_size, 10000)
        self.assertEqual(font_path.read_bytes()[:4], b'\x00\x01\x00\x00')
        import tempfile
        from pathlib import Path
        with self.app.app_context():
            with tempfile.TemporaryDirectory() as temp_dir:
                out = Path(temp_dir) / 'model.pdf'
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, out)
                self.assertTrue(out.exists())
                self.assertGreater(out.stat().st_size, 1000)
        with self.app.app_context():
            report = self.application_module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
            with tempfile.TemporaryDirectory() as temp_dir:
                out = Path(temp_dir) / 'study.pdf'
                with patch.dict('sys.modules', {'playwright': None, 'playwright.sync_api': None}):
                    self.application_module.generate_financial_pdf(report, out)
                self.assertTrue(out.exists())
                self.assertGreater(out.stat().st_size, 100)

    def test_financial_schedules_state_their_own_totals_and_stop_at_their_own_period(self):
        """Five faults in the financial study, each of which showed a wrong figure as a right one.

        A percentage column that summed to less than 100% still looked complete; a schedule table
        printed one row per project year regardless of the period entered for it; a sale exit could
        be configured on a project that has no sellable units and stayed silently zero; and no
        screen stated how any derived figure had been arrived at.
        """
        index_source = read_frontend_text()

        # 1. Both percentage columns of the stage table state their sum and what is unassigned.
        self.assertIn('id="scheduleCostPctTotal"', index_source)
        self.assertIn('id="scheduleDevPctTotal"', index_source)
        self.assertIn('id="scheduleCostTotalValue"', index_source)
        self.assertIn('id="scheduleDevTotalValue"', index_source)
        self.assertIn('function renderSchedulePercentTotals(rows, costValueTotal, devValueTotal)',
                      index_source)
        self.assertIn('غير موزَّع من نسبة تكلفة التطوير:', index_source)
        self.assertIn('غير موزَّع من نسبة دفعة المطور:', index_source)
        self.assertIn('renderSchedulePercentTotals(scheduleRows, scheduleCostValueTotal, scheduleDevValueTotal);',
                      index_source)
        # A tfoot row must reach the exported PDF, or the totals exist only on screen.
        self.assertIn("table.querySelectorAll('tbody tr,tfoot tr')", index_source)

        # 2. The sale exit belongs to a project that has sellable units, and its state is stated.
        self.assertIn('const saleModeOn = projectModeFlags().sales;', index_source)
        self.assertIn("const saleExitMethod = saleModeOn ? (val('saleExitMethod') || 'none') : 'none';",
                      index_source)
        self.assertIn("setWrapVisible('saleExitMethodWrap', exitOn && saleModeOn);", index_source)
        self.assertIn('id="saleExitAreaReference"', index_source)
        self.assertIn('function renderSaleExitStatus({', index_source)
        self.assertIn('لا يوجد تخارج بيعي: وحدات المشروع تأجيرية بالكامل.', index_source)
        self.assertIn('التخارج البيعي مطبق بقيمة صفر:', index_source)

        # 3. الإيضاحات is client-written optional text, never an automatically calculated table.
        self.assertIn('<textarea id="financialClarifications"', index_source)
        self.assertIn("const clarificationText = val('financialClarifications').trim();", index_source)
        self.assertIn('const clarificationReportSection = clarificationText', index_source)
        self.assertNotIn('id="clarificationsTable"', index_source)
        self.assertNotIn('function renderClarifications(facts)', index_source)
        self.assertNotIn('renderClarifications({', index_source)

        # 4 and 5. Each schedule stops strictly at the end year entered for that schedule.
        self.assertIn('function financeMovementRows(projected, financeOn, repaymentStartYear, repaymentYears)',
                      index_source)
        self.assertIn('function fundFeeScheduleRows(projected, fundFeesOn, feeEndYear)', index_source)
        self.assertIn('return projected.filter(row => row.year <= plannedEnd);', index_source)
        self.assertIn('financeMovementRows(projected, financeOn, financeRepaymentStartYear, financeRepaymentYears)',
                      index_source)
        self.assertIn('fundFeeScheduleRows(projected, fundFeesOn, fundFeeEndYear)', index_source)
        # The tables must no longer render straight from the full projection.
        self.assertNotIn(
            "if (debtTb) debtTb.innerHTML = projected.map(r => `<tr><td>${r.year}</td>", index_source)
        self.assertNotIn(
            "if (fundTb) fundTb.innerHTML = projected.map(r => `<tr><td>${r.year}</td>", index_source)

    def test_location_roads_timestamp_and_financial_schedule_guards(self):
        index_source = read_frontend_text()
        self.assertNotIn("infoBtn.textContent = 'جلب معلومات المسافة والمدة'", index_source)
        self.assertIn('location_data_fetched_at', index_source)
        self.assertIn('formatLocationDataFetchedAt', index_source)
        self.assertEqual(
            self.application_module.maps_service.normalize_access_road_names(
                'شارع الشمس\nشارع الشاطئ و الشمس\nشارع الشمس'),
            ['شارع الشمس', 'شارع الشاطئ'])
        self.assertIn("'location_data_fetched_at'", read_module_source('db.py'))
        stamped = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide"><img src="##MAP_OVERVIEW##"></div>', 'map_overview',
            {'location_data_fetched_at': '2026-01-02T10:30:00Z'}, {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'})
        self.assertIn('تم قياس زمن القيادة بتاريخ 02 / 01 / 2026 م (م = ميلادي) الساعة 01:30 م', stamped)
        self.assertNotIn('آخر تحديث لبيانات الموقع', stamped)
        self.assertNotIn('بتوقيت السعودية', stamped)
        self.assertEqual(
            self.application_module.slide_engine._location_data_timestamp(
                {'location_data_fetched_at': '2026-01-02T00:05:00Z'}
            ),
            '02 / 01 / 2026 م (م = ميلادي) الساعة 03:05 ص',
        )
        self.assertIn('input.dataset.lastValidValue', index_source)
        self.assertIn('تجاوز 100%', index_source)
        finance_body = index_source.split('function financeMovementRows(', 1)[1].split('function fundFeeScheduleRows(', 1)[0]
        self.assertNotIn('activeEnd', finance_body)
        self.assertIn('row.year <= plannedEnd', finance_body)
        fund_body = index_source.split('function fundFeeScheduleRows(', 1)[1].split('function addCost(', 1)[0]
        self.assertNotIn('activeEnd', fund_body)
        self.assertIn('row.year <= plannedEnd', fund_body)

    def test_land_document_normalizer_keeps_each_parcel_and_four_directions(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-7',
                'plot_number': '7',
                'directions': {'north': {'street_name': 'طريق شمالي', 'source': 'regulation_table'}},
                'survey_coordinates': [{'point': '1', 'eastings': '510180.849', 'northings': '2939234.840'}]
            }, {
                'parcel_id': 'P-8',
                'plot_number': '8',
                'directions': {'غرب': {'street_name': 'شارع غربي'}}
            }]
        })
        self.assertEqual([item['parcel_id'] for item in result['parcels']], ['P-7', 'P-8'])
        self.assertEqual(result['parcels'][0]['directions']['north']['street_name'], 'طريق شمالي')
        self.assertIn('west', result['parcels'][1]['directions'])
        self.assertIn('east', result['parcels'][0]['directions'])
        self.assertEqual(result['survey_coordinates'][0]['source'], 'regulation_table')
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '510180.849')

    def test_parcel_path_normalizes_facades_deed_and_blocks_approved_area(self):
        """The scalar normalizers must run on the ``parcels`` path, not only on the legacy one."""
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'plan_number': '3/س/125',
                # A direction word must never survive in the numeric facade field.
                'facades_count': 'جنوبية',
                'north_direction': 'يميل قليلًا نحو الشمال الغربي',
                'deed_number': 'غير مذكور',
                'approved_financial_area_sqm': 4321,
                'directions': {'south': {'street_name': 'شارع جنوبي'}},
            }],
            'land_and_building_summary': 'ملخص تفصيلي مسترسل عن الأرض والاشتراطات.',
        }, 'صك رقم 260629004505 وتاريخ الصك 1446/03/12 لقطعة رقم 9991')
        parcel = result['parcels'][0]

        # "جنوبية" is rejected as a count, then the count is rebuilt from the one street side.
        self.assertEqual(parcel['facades_count'], '1')
        self.assertEqual(parcel['facades_directions'], 'جنوبية')
        self.assertEqual(parcel['north_direction'], 'شمال غربي')
        # Placeholder wording is dropped, then the regex fallback fills the real values.
        self.assertEqual(parcel['deed_number'], '260629004505')
        self.assertEqual(parcel['deed_date'], '1446/03/12')
        self.assertEqual(result['plan_number'], '3/س/125')
        # The approved financial-study area is the client's input and must never be returned.
        self.assertNotIn('approved_financial_area', result)
        self.assertEqual(result['land_and_building_summary'], 'ملخص تفصيلي مسترسل عن الأرض والاشتراطات.')

    def test_hijri_dates_are_extracted_and_never_fed_to_a_date_input(self):
        """Saudi deeds are dated in Hijri; <input type="date"> silently drops those values."""
        find = self.application_module._find_document_date
        self.assertEqual(find('صك رقم 260629004505 وتاريخ 1446/03/12هـ'), '1446/03/12')
        self.assertEqual(find('تاريخ الصك 1446-03-12'), '1446/03/12')
        self.assertEqual(find('بتاريخ 12/03/1446 قطعة رقم أ'), '1446/03/12')
        self.assertEqual(find('وتاريخ ١٤٤٦/٠٣/١٢ هـ'), '1446/03/12')
        self.assertEqual(find('صادر بتاريخ 2025/09/30'), '2025/09/30')
        self.assertEqual(find('لا يوجد تاريخ هنا'), '')

        # deed_date must stay text so Hijri values survive; <input type="date"> would drop them.
        # (croquis_expiry_date was retired, and the client-side date parser went with its badge.)
        self.assertEqual(next(f for f in db.PREBUILT_FIELDS if f['key'] == 'deed_date')['type'], 'text')

        index_source = read_frontend_text()
        self.assertNotIn('const expDate = new Date(input.value);', index_source)
        self.assertNotIn('parseDocumentDate', index_source)

    def test_plan_number_falls_back_to_the_document_text(self):
        module = self.application_module
        for text, expected in (
            ('المخطط رقم 3/س/125', '3/س/125'),
            ('رقم المخطط: 1406/ب', '1406/ب'),
            ('مخطط خاص بدون رقم', ''),
        ):
            parcel = {'plan_number': ''}
            module._normalize_parcel_scalar_fields(parcel, text)
            self.assertEqual(parcel['plan_number'], expected, text)

    def test_building_rules_are_split_into_ratio_and_setbacks_fields(self):
        """The visible form separates ratios from setbacks without losing legacy payload support."""
        index_source = read_frontend_text()
        self.assertNotIn('building_ratio_setbacks: parcel.building_ratio || parcel.setbacks', index_source)
        self.assertIn('building_ratio_coverage: parcel.building_ratio_coverage || buildingRatioCoverageText', index_source)
        self.assertIn('setbacks: parcel.setbacks || setbacksText', index_source)
        self.assertIn('building_ratio_setbacks: parcel.building_ratio_setbacks || buildingRulesText', index_source)
        for label in ('نسبة البناء', 'نسبة التغطية', 'معامل مسطح البناء (FAR)'):
            self.assertIn("['" + label + "'", index_source)
        self.assertIn("const setbacksText = String(parcel.setbacks || '').trim() || directionSetbacksText;", index_source)
        self.assertIn('directionSetbacksText', index_source)

        app_source = read_module_source('app.py')
        self.assertIn('"coverage_ratio": ""', app_source)
        self.assertIn('"floor_area_ratio": ""', app_source)
        self.assertIn('لا تكتب «60%» وحدها', app_source)
        self.assertIn('غير محددة في المرجع المتاح', app_source)
        self.assertIn('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', app_source)
        self.assertIn("os.environ.get('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', '0')", app_source)
        self.assertIn('لا تكتب في أي حقل عبارات مثل «صفحة كذا»', app_source)

    def test_land_use_status_is_split_out_of_allowed_uses_text(self):
        module = self.application_module
        self.assertEqual(module.normalize_land_use_status('غير مسموح في هذه المنطقة'), 'غير مسموح')
        self.assertEqual(module.normalize_land_use_status('غير محسوم'), 'غير محسوم')
        status, text = module.split_land_use_status_text('حالة استخدام المشروع: غير مسموح\nسكني وتجاري')
        self.assertEqual(status, 'غير مسموح')
        self.assertEqual(text, 'سكني وتجاري')
        status_only, empty_text = module.split_land_use_status_text('استخدام الأرض: مسموح')
        self.assertEqual(status_only, 'مسموح')
        self.assertEqual(empty_text, '')
        self.assertEqual(
            module.resolve_land_use_status(
                'سكني',
                'الاستخدام المسموح للموقع هو سكني ترفيهي سياحي متنوع للجزء المطل على طريق الكورنيش، وسكني عمائر للجزء المتبقي.'
            ),
            'مسموح',
        )
        ignored = module.apply_entered_land_use_status({
            'allowed_uses': 'سكني ترفيهي سياحي',
            'land_use_status': 'غير محسوم',
            'parcels': [{'allowed_uses': 'سكني ترفيهي سياحي', 'land_use_status': 'غير محسوم'}],
        }, 'سكني')
        self.assertEqual(ignored['land_use_status'], 'مسموح')
        self.assertEqual(ignored['parcels'][0]['land_use_status'], 'مسموح')

    def test_land_result_exposes_split_usage_fields_without_page_references(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'building_ratio': '60% من مساحة الأرض',
                'coverage_ratio': '50%',
                'floor_area_ratio': '2.5',
                'setbacks': 'أمامي 6م؛ خلفي 3م',
                'allowed_uses': 'حالة استخدام المشروع: غير محسوم\nسكني ترفيهي سياحي',
                'land_use_status': 'غير محسوم',
                'regulatory_constraints': 'اشتراطات المواقف: موقف لكل وحدة وفق اشتراطات1 صفحة 12',
                'summary': 'الاشتراطات وفق اشتراطات2 صفحة 44 واضحة.',
            }]
        }, project_type='سكني')
        parcel = result['parcels'][0]
        self.assertIn('نسبة البناء', parcel['building_ratio_coverage'])
        self.assertEqual(parcel['setbacks'], 'أمامي 6م؛ خلفي 3م')
        self.assertEqual(parcel['land_use_status'], 'مسموح')
        self.assertIn('موقف لكل وحدة', parcel['regulatory_constraints'])
        self.assertNotIn('صفحة 12', parcel['regulatory_constraints'])
        self.assertNotIn('صفحة 44', parcel['summary'])
        self.assertEqual(parcel['allowed_uses'], 'سكني ترفيهي سياحي')
        self.assertEqual(result['allowed_uses'], 'سكني ترفيهي سياحي')

    def test_full_regulation_evidence_includes_unmatched_pages_and_tables(self):
        module = self.application_module
        records = [
            {'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 1, 'text': 'قاعدة نسبة البناء', 'has_table': False},
            {'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 2, 'text': 'قاعدة غير مطابقة للكلمات المدخلة', 'has_table': True},
            {'name': 'اشتراطات2.pdf', 'path': 'two.pdf', 'page': 1, 'text': 'قاعدة الارتداد', 'has_table': False},
        ]
        with patch.object(module, '_build_regulation_page_index', return_value=records):
            package, warnings = module.search_official_regulations_evidence('كلمة لا تطابق', {})
        self.assertEqual(warnings, [])
        first = next(item for item in package['documents'] if item['name'] == 'اشتراطات1.pdf')
        self.assertIn('قاعدة غير مطابقة للكلمات المدخلة', first['context'])
        self.assertIn(2, first['text_pages'])
        self.assertEqual(package['table_pages'][0]['page'], 2)
        self.assertEqual({item['name'] for item in package['documents']}, {'اشتراطات1.pdf', 'اشتراطات2.pdf'})

    def test_full_regulation_table_pages_are_not_dropped_when_batched(self):
        module = self.application_module
        pages = [
            {'path': 'one.pdf', 'name': 'اشتراطات1.pdf', 'page': page}
            for page in (7, 8, 9, 10, 11)
        ]
        with patch.object(module, 'REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE', 2):
            batches = module.split_regulation_table_batches(pages)
        self.assertEqual([[item['page'] for item in batch] for batch in batches], [[7, 8], [9, 10], [11]])
        self.assertEqual(
            [item['page'] for batch in batches for item in batch],
            [item['page'] for item in pages],
        )

    def test_land_analysis_site_context_uses_map_fields(self):
        module = self.application_module
        with patch.object(module, '_collect_site_fields', return_value=(
            {'location_detail': 'عنوان الموقع', 'main_roads': 'طريق رئيسي'},
            [{'name': 'معلم قريب'}], [], [], [], [], None, {}
        )):
            context, warnings = module.build_land_analysis_site_context({
                'locationAddress': 'https://www.google.com/maps/@24,46,17z',
                'locationLat': 24,
                'locationLng': 46,
                'includeMapContext': True,
                'siteContext': {'project_type': 'سكني'},
            }, self.tenant_a, 24, 46)
        self.assertEqual(warnings, [])
        self.assertEqual(context['location_detail'], 'عنوان الموقع')
        self.assertEqual(context['main_roads'], 'طريق رئيسي')
        self.assertEqual(context['nearby_landmarks_data'][0]['name'], 'معلم قريب')

    def test_facade_count_accepts_real_counts_and_rejects_directions(self):
        normalize = self.application_module.normalize_facades_count
        self.assertEqual(normalize(4), '4')
        self.assertEqual(normalize('واجهتين'), '2')
        self.assertEqual(normalize('بلك كامل'), '4')
        self.assertEqual(normalize('شمالية وغربية'), '')
        self.assertEqual(normalize('', 'الأرض زاوية على شارعين'), '2')

    def test_facades_are_only_the_sides_that_front_a_street(self):
        """All plots have four boundaries, so naming four directions says nothing. Only the
        boundaries that border a street are facades."""
        module = self.application_module
        directions = {
            'north': {'street_name': 'شارع الأمير ماجد', 'street_width_m': 30},
            'south': {'street_name': 'قطعة رقم 12', 'uses': 'جار'},
            'east': {'street_name': '', 'street_width_m': 15},
            'west': {'street_name': 'أرض مجاورة'},
        }
        self.assertEqual(module.facade_directions_from_streets(directions), 'شمالية، شرقية')
        self.assertEqual(module.facade_directions_from_streets({}), '')

        # The count is derived from those sides when the model leaves it blank.
        parcel = {'facades_count': '', 'directions': directions}
        module._normalize_parcel_scalar_fields(parcel, '')
        self.assertEqual(parcel['facades_directions'], 'شمالية، شرقية')
        self.assertEqual(parcel['facades_count'], '2')

        wrong_count = {'facades_count': '4', 'directions': directions}
        module._normalize_parcel_scalar_fields(wrong_count, '')
        self.assertEqual(wrong_count['facades_count'], '2')

    def test_truncated_analysis_is_rejected_with_an_explicit_reason(self):
        """A rejected extraction changes no field, so it must not look like a silent no-op."""
        module = self.application_module
        source = read_module_source('app.py')
        self.assertIn('_call_land_analysis_model(', source)
        for reason in ('truncated', 'invalid_json', 'insufficient_credit'):
            self.assertIn(f"'failureReason': '{reason}'", source)
        self.assertIn('ولهذا لم تتغير البيانات', source)

        index_source = read_frontend_text()
        self.assertIn("'لم يتم تحديث أي حقل: ' + reason", index_source)
        self.assertIn('res.failureReason', index_source)
        self.assertIn("' حقلًا. راجع النتائج قبل الاعتماد.'", index_source)

    def test_land_analysis_lowers_the_cap_when_the_provider_cannot_afford_it(self):
        """OpenRouter reserves max_tokens against the balance, so an over-large cap is refused
        with 402 even when the real answer would be short."""
        module = self.application_module
        # A default the account can actually pay for; the retry only ever walks the cap down.
        self.assertLessEqual(module.LAND_ANALYSIS_MAX_TOKENS, 16000)

        refusal = {'error': {'code': 402, 'message': (
            'This request requires more credits, or fewer max_tokens. '
            'You requested up to 60000 tokens, but can only afford 25898')}}
        success = {'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}]}
        caps = []

        def fake_call(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, usage_ctx=None):
            caps.append(max_tokens)
            return refusal if max_tokens > 25898 else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call):
            res, cap, error = module._call_land_analysis_model('s', 'u', 60000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(error, '')
        self.assertEqual(caps[0], 60000)
        self.assertLessEqual(caps[1], 25898)
        self.assertLess(cap, 60000)

        # A failure that is not about credit must be reported, not retried in a loop.
        with patch.object(module, 'call_openrouter_chat',
                          return_value={'error': {'message': 'model not found'}}) as once:
            _, _, error = module._call_land_analysis_model('s', 'u', 12000)
        self.assertEqual(once.call_count, 1)
        self.assertIn('model not found', error)

        source = read_module_source('app.py')
        self.assertIn('رصيد OpenRouter لا يكفي', source)
        self.assertIn("'providerError': model_error", source)

    def test_land_analysis_retries_an_empty_provider_response(self):
        module = self.application_module
        empty = {'error': {'message': 'مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP 200)'}}
        success = {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
        with patch.object(module, 'call_openrouter_chat', side_effect=[empty, success]) as call, \
                patch.object(module.time, 'sleep'):
            res, cap, error = module._call_land_analysis_model('s', 'u', 16000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(cap, 16000)
        self.assertEqual(error, '')
        self.assertEqual(call.call_count, 2)

    def test_land_analysis_retries_without_json_mode_after_output_format_block(self):
        """Anthropic and some OpenRouter fallbacks reject json_object with output_format
        content filtering, which used to abort the whole croquis analysis."""
        module = self.application_module
        blocked = {'error': {'message': (
            '[400] Provider returned error '
            '{"type":"error","error":{"type":"invalid_request_error",'
            '"message":"Output blocked by content filtering policy","code":"output_format"}}'
        )}}
        success = {'choices': [{'message': {'content': '{"plot_number":"9991"}'}, 'finish_reason': 'stop'}]}
        formats = []

        def fake_call(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None,
                      timeout=300, reasoning_effort=None, response_format=None, provider=None, usage_ctx=None):
            formats.append(response_format)
            return blocked if response_format else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call) as call:
            res, cap, error = module._call_land_analysis_model('s', 'u', 16000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(error, '')
        self.assertEqual(cap, 16000)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(formats[0], {'type': 'json_object'})
        self.assertIsNone(formats[1])
        self.assertEqual(module._get_chat_response_text(res), '{"plot_number":"9991"}')

    def test_land_analysis_reads_json_from_reasoning_when_content_is_empty(self):
        """Reasoning models often spend the reply on reasoning and leave message.content empty."""
        module = self.application_module
        payload = json.dumps({
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'area_sqm': 3000,
                'survey_coordinates': [{'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'}],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }, ensure_ascii=False)
        response = {
            'choices': [{
                'finish_reason': 'stop',
                'message': {
                    'content': '',
                    'reasoning': 'thinking first then answer\n' + payload,
                },
            }]
        }
        self.assertEqual(module.parse_json_object(module._get_chat_response_text(response))['parcels'][0]['plot_number'], '9991')

        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(module, '_call_land_analysis_model', return_value=(response, 9000, '')):
            result = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()['extractedData']['plot_number_croquis'], '9991')

    def test_live_land_analysis_returns_a_job_and_is_polled(self):
        """The hosting proxy fabricates a 404 if extract-croquis stays open for minutes."""
        module = self.application_module
        model_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'survey_coordinates': [{'point': '1', 'eastings': '1', 'northings': '2'}],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }
        provider_response = {
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(model_payload, ensure_ascii=False)}}]
        }
        client = self.app.test_client()
        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(module, '_call_land_analysis_model', return_value=(provider_response, 9000, '')):
            started = client.post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'background': True,
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })
            self.assertEqual(started.status_code, 202, started.get_json())
            job_id = started.get_json()['jobId']
            self.assertTrue(job_id)
            job = None
            for _ in range(80):
                polled = client.get('/api/extract-croquis/' + job_id, headers=self._headers(self.token_a))
                self.assertEqual(polled.status_code, 200, polled.get_json())
                job = polled.get_json()
                if job.get('status') in ('completed', 'failed'):
                    break
                time.sleep(0.05)
        self.assertEqual(job['status'], 'completed', job)
        self.assertTrue(job['success'])
        self.assertEqual(job['extractedData']['plot_number_croquis'], '9991')
        self.assertNotIn('rawText', job)

        foreign = client.get('/api/extract-croquis/' + job_id, headers=self._headers(self.token_b))
        self.assertEqual(foreign.status_code, 404)

        index_source = read_frontend_text()
        self.assertIn("api('GET', '/api/extract-croquis/' + encodeURIComponent(jobId))", index_source)
        self.assertIn('res.jobId', index_source)

    def test_land_prompt_forbids_ai_written_approved_area_and_demands_narrative(self):
        source = read_module_source('app.py')
        self.assertNotIn('"approved_financial_area_sqm": null', source)
        self.assertIn('"subdivision_number": ""', source)
        self.assertIn('"deed_date": ""', source)
        self.assertIn('"facades_directions": ""', source)
        self.assertIn('عدد الحدود المطلة على شوارع فقط', source)
        # Trimmed from 250 words: the longer narrative pushed the JSON past the token cap, and a
        # truncated response is discarded whole.
        self.assertIn('١٨٠ كلمة على الأقل', source)
        self.assertIn('وليس قائمة حقول مفصولة بشرطات', source)
        self.assertIn('قائمة الاستخدامات المسموحة تنظيميًا', source)

    def test_regulation_lookup_skips_index_pages_and_strips_page_furniture(self):
        module = self.application_module
        index_page = 'نسبة البناء ' + ('.' * 30) + ' 36\nالارتدادات ' + ('.' * 30) + ' 37\nالتغطية ' + ('.' * 30) + ' 38'
        self.assertTrue(module._is_regulation_index_page(index_page))
        self.assertTrue(module._is_regulation_index_page(''))
        self.assertFalse(module._is_regulation_index_page('نسبة البناء هي النسبة المئوية لمساحة الحد الأقصى'))

        noisy = 'المخطط المحلي لمحافظة جدة1447 هـ\nم ص 25 من197\nنسبة البناء 60%'
        cleaned = module._clean_regulation_text(noisy)
        self.assertIn('نسبة البناء 60%', cleaned)
        self.assertNotIn('من197', cleaned)

        # Pages carrying the conditions must outrank generic prose.
        self.assertGreater(
            module._score_regulation_page('نسبة البناء 60% وعدد الطوابق 5 وارتداد أمامي', []),
            module._score_regulation_page('مقدمة عامة عن الوثيقة', []))

    def test_regulation_lookup_reports_missing_files_instead_of_failing_silently(self):
        module = self.application_module
        with patch.object(module, 'regulation_pdf_paths', return_value=[]):
            context, table_pages, warnings = module.search_official_regulations_pdf('ت ر1')
        self.assertEqual(context, '')
        self.assertEqual(table_pages, [])
        self.assertTrue(warnings, 'a missing regulation file must surface a warning')
        self.assertIn('اشتراطات1.pdf', warnings[0])

        source = read_module_source('app.py')
        # The stale hardcoded filenames are gone, along with the first-two-pages-then-break scan.
        self.assertNotIn('Document_LocalPlan_1447.pdf', source)
        self.assertNotIn('ExecutiveRegulations-1447-2025-2.pdf', source)
        self.assertNotIn('search_jeddah_official_regulations_pdf', source)
        # Client documents stay vision-only; the regulation arrives as trusted text + table images.
        self.assertIn('لديك نوعان من المدخلات', source)
        self.assertIn('نص هذا الجدول يُستخرج بترتيب معكوس', source)
        self.assertIn('نتائج استخلاص الاشتراطات من المحتوى الكامل للملفين', source)

    @unittest.skipUnless((ROOT / 'اشتراطات1.pdf').exists(), 'regulation PDFs not present')
    def test_regulation_lookup_returns_real_condition_pages(self):
        context, table_pages, warnings = self.application_module.search_official_regulations_pdf('ت ر1 تجاري سكني')
        self.assertEqual(warnings, [])
        # Far more usable text than the old 4 KB of index pages, and none of the furniture.
        self.assertGreater(len(context), 6000)
        self.assertNotIn('من197', context)
        self.assertNotIn('......', context)
        self.assertIn('نسبة البناء', context)
        # Zoning tables extract in reversed order, so they must ride along as images.
        self.assertTrue(table_pages)
        parts, render_warnings = self.application_module.render_regulation_table_pages(table_pages[:2])
        self.assertEqual(render_warnings, [])
        self.assertEqual(len(parts), 4)
        self.assertTrue(parts[1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_regulation_evidence_can_be_limited_per_file_when_configured(self):
        module = self.application_module
        records = [
            {
                'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 12,
                'text': 'نسبة البناء والاستخدامات والمواقف سكني', 'has_table': True,
            },
            {
                'name': 'اشتراطات2.pdf', 'path': 'two.pdf', 'page': 44,
                'text': 'ارتداد وتغطية وعدد الطوابق وارتفاع مسطح البناء', 'has_table': True,
            },
            {
                'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 13,
                'text': 'مقدمة عامة عن الوثيقة', 'has_table': False,
            },
        ]
        with patch.object(module, '_build_regulation_page_index', return_value=records), \
                patch.object(module, 'REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', 1), \
                patch.object(module, 'REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE', 1):
            package, warnings = module.search_official_regulations_evidence(
                'سكني', {'area_sqm': 3000, 'land_use': 'سكني'}
            )

        self.assertEqual(warnings, [])
        self.assertEqual([item['name'] for item in package['documents']], ['اشتراطات1.pdf', 'اشتراطات2.pdf'])
        self.assertEqual([item['table_pages'] for item in package['documents']], [[12], [44]])
        self.assertEqual({item['name'] for item in package['table_pages']}, {'اشتراطات1.pdf', 'اشتراطات2.pdf'})
        self.assertIn('نسبة البناء والاستخدامات والمواقف', package['context'])
        self.assertIn('ارتداد وتغطية وعدد الطوابق', package['context'])
        self.assertNotIn('مقدمة عامة عن الوثيقة', package['context'])
