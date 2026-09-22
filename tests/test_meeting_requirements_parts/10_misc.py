class MeetingRequirementsTestsPart09(MeetingRequirementsTests):

    def test_financial_sol_templates_reserve_managed_header_space(self):
        engine = self.application_module.slide_engine
        source = {
            'project_name': 'مشروع الاختبار',
            'financial_study_model': {
                'tables': {
                    'sensitivityTable': [
                        {'السيناريو': 'أساسي', 'إجمالي الإيرادات': '100,000', 'إجمالي تكلفة المشروع': '50,000'},
                    ],
                },
            },
        }
        slide = {'title': 'جدول الدراسة المالية', 'content_source': 'financial_table:components:1:1'}
        table_html = engine._build_sol_table_slide(slide, source, {})
        heatmap_html = engine._build_sol_heatmap_slide(
            {'title': 'تحليل الحساسية', 'chart_type': 'heatmap'}, source, {})
        self.assertIn('padding:0 36px;margin-top:70px;', table_html)
        self.assertIn('padding:0 36px;margin-top:70px;', heatmap_html)

    def test_executive_summary_does_not_leave_an_empty_image_panel_or_clip_long_text(self):
        engine = self.application_module.slide_engine
        summary = ('البيانات الأساسية\n' + ('نص معتمد للمشروع يشرح البيانات والموقع دون إضافة حقائق جديدة. ' * 24))
        html = engine._build_structured_fallback_slide(
            {'title': 'الملخص التنفيذي', 'content_source': 'executive_content.summary'},
            {'project_name': 'مشروع الاختبار', 'executive_content': {'summary': summary}},
            {},
        )
        self.assertIn('data-exec-analysis', html)
        self.assertIn('البيانات الأساسية', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('##MOODBOARD_1##', html)
        self.assertNotIn('المعتمد دون إضافة أو تكرار', html)

    def test_revenue_table_linked_component_can_be_changed_and_cleared(self):
        """Selecting a linked component in table 4 (بنود الإيرادات) must remain editable:
        changing to another component or choosing 'غير مرتبط بمكون' must not revert to
        the previously saved componentId."""
        index_source = read_frontend_text()
        self.assertIn('const compSelect = tr.querySelector(\'[data-field="component"] select\');', index_source)
        self.assertIn('compSelect.addEventListener(\'change\', onCompChange);', index_source)
        self.assertIn('tr.dataset.componentId = compSelect.value || \'\';', index_source)
        self.assertIn('let currentId = (sel.options && sel.options.length > 0) ? (sel.value || \'\') : (tr.dataset.componentId || \'\');', index_source)
        self.assertIn('const idx = sel ? (sel.value || \'\') : (tr?.dataset?.componentId || \'\');', index_source)


    # ── Contextual designer-chat regression tests ──────────────────────────────

    def test_designer_chat_ask_returns_no_mutation_and_no_navigation(self):
        """When the model returns ask, the server must not edit any slide and must
        return action='ask'. The client must not navigate to a slide on ask/chat_only."""
        client = self.app.test_client()
        slides = [
            {'html': '<div class="slide"><h1>الغلاف</h1></div>', 'title': 'الغلاف', 'type': 'cover'},
            {'html': '<div class="slide"><h1>المحتوى</h1></div>', 'title': 'المحتوى', 'type': 'content'},
        ]
        plan = json.dumps({
            'response': 'أي شريحة تقصد؟',
            'actions': [{'tool': 'ask', 'params': {'question': 'أي شريحة تقصد؟'}}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}):
            resp = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                'message': '5', 'slidesData': slides, 'slideIndex': 0,
            })
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()['data']
        self.assertEqual(data['action'], 'ask')
        # Slides must be unchanged
        self.assertEqual(data['slidesData'], slides)
        # Client must handle ask/chat_only without navigating
        index_source = read_frontend_text()
        self.assertIn("if (reply.action === 'ask' || reply.action === 'chat_only') {", index_source)

    def test_designer_chat_chat_only_returns_no_mutation(self):
        """chat_only must return action='chat_only' and leave slides untouched."""
        client = self.app.test_client()
        slides = [{'html': '<div class="slide"><h1>شريحة</h1></div>', 'title': 'شريحة', 'type': 'content'}]
        plan = json.dumps({
            'response': 'تم الإلغاء.',
            'actions': [{'tool': 'chat_only', 'params': {}}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}):
            resp = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                'message': 'لا شيء', 'slidesData': slides, 'slideIndex': 0,
            })
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()['data']
        self.assertEqual(data['action'], 'chat_only')
        # chat_only does not return slidesData (no mutation occurred)
        self.assertNotIn('slidesData', data)

    def test_designer_chat_invalid_plan_returns_502_without_mutation(self):
        """An empty or non-list actions field must return 502 DESIGNER_INVALID_PLAN
        and must not mutate any slide."""
        client = self.app.test_client()
        slides = [{'html': '<div class="slide"><h1>شريحة</h1></div>', 'title': 'شريحة', 'type': 'content'}]
        for bad_plan in [
            json.dumps({'response': 'ok', 'actions': []}, ensure_ascii=False),
            json.dumps({'response': 'ok'}, ensure_ascii=False),
            'not json at all',
        ]:
            with patch.object(self.application_module, 'call_zai_chat',
                              return_value={'choices': [{'message': {'content': bad_plan}}]}):
                resp = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                    'message': 'عدل الشريحة', 'slidesData': slides, 'slideIndex': 0,
                })
            self.assertEqual(resp.status_code, 502, f'Expected 502 for plan: {bad_plan!r}')
            body = resp.get_json()
            self.assertFalse(body.get('success'))
            self.assertEqual(body.get('error_code'), 'DESIGNER_INVALID_PLAN')

    def test_designer_chat_number_in_message_does_not_force_slide_navigation(self):
        """A bare number in the message must not cause the client to navigate to that
        slide index before the server responds. The client sends it as-is and lets the
        model interpret context."""
        index_source = read_frontend_text()
        chat_body = index_source.split('async function sendTenantDesignerChat() {', 1)[1]
        chat_body = chat_body.split('\n    async function ', 1)[0]
        # The old client-side regex that detected slide numbers and called selectTenantSlide
        # before the server responded is gone.
        self.assertNotIn('detectSlideIndexesFromMessage(message)', chat_body)
        self.assertNotIn('ALL_SLIDES_REGEX', chat_body)
        # The scope is determined by the UI toggle only, not by message content.
        self.assertIn("const targetScope = tenantChatSlideScope === 'all' ? 'all' : 'auto';", chat_body)
        self.assertIn('const target1BasedIndexes = [];', chat_body)

    def test_executor_navigation_only_on_editing_phase_signal(self):
        """The client must navigate to a slide only when the polling response carries
        phase='editing' with a valid activeSlideIndex, and must deduplicate."""
        index_source = read_frontend_text()
        poll_body = index_source.split('async function requestTenantDesignerChat(', 1)[1]
        poll_body = poll_body.split('\n    async function ', 1)[0]
        self.assertIn("result?.phase === 'editing'", poll_body)
        self.assertIn('result.activeSlideIndex', poll_body)
        self.assertIn('lastExecutionTarget', poll_body)
        self.assertIn('selectTenantSlide(result.activeSlideIndex)', poll_body)

    def test_watermark_survives_strip_market_slide_media(self):
        """_strip_market_slide_media must not remove a slide-watermark element."""
        engine = self.application_module.slide_engine
        app_mod = self.application_module
        logo_url = '/uploads/creative/tenant-x/logo.png'
        html = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', logo_url
        )
        self.assertIn('data-slide-watermark="true"', html)
        stripped = engine._strip_market_slide_media(html)
        self.assertIn('data-slide-watermark="true"', stripped,
                      '_strip_market_slide_media must not remove the watermark element')
        self.assertIn(logo_url, stripped)

    def test_watermark_overlay_does_not_block_manual_slide_editing(self):
        """Only the visible watermark logo may receive pointer events in edit mode."""
        index_source = read_frontend_text()
        watermark_css = index_source.split(
            '/* Keep the full-slide watermark overlay click-through while editing;', 1
        )[1].split('.slide-resize-handle', 1)[0]
        self.assertIn('pointer-events: none !important;', watermark_css)
        self.assertIn('.slide-element-editing .slide-watermark > img,', watermark_css)
        self.assertIn('[data-slide-watermark="true"] > img', watermark_css)
        self.assertIn('pointer-events: auto !important;', watermark_css)

    def test_watermark_survives_renumber_presentation_slides(self):
        """renumber_presentation_slides must not strip the watermark from a slide."""
        engine = self.application_module.slide_engine
        app_mod = self.application_module
        logo_url = '/uploads/creative/tenant-x/logo.png'
        html = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', logo_url
        )
        slides = [{'html': html, 'title': 'شريحة', 'type': 'content', 'is_custom': True}]
        renumbered = engine.renumber_presentation_slides(slides)
        self.assertIn('data-slide-watermark="true"', renumbered[0]['html'],
                      'renumber_presentation_slides must preserve the watermark')

    def test_watermark_add_save_reload_cycle(self):
        """A watermark added via designer-chat must survive a presentation PUT and GET."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        app_mod = self.application_module
        logo_url = '/uploads/creative/tenant-x/logo.png'
        watermarked_html = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', logo_url
        )
        # Create a presentation with a watermarked slide
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض العلامة المائية',
            'projectData': {},
            'slidesData': [{'html': watermarked_html, 'title': 'شريحة', 'type': 'content', 'is_custom': True}],
            'slideCount': 1,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        pres_id = created.get_json()['presentationId']

        # Reload and verify watermark is still there
        fetched = client.get(f'/api/presentations/{pres_id}', headers=headers)
        self.assertEqual(fetched.status_code, 200, fetched.get_json())
        pres_data = fetched.get_json()['presentation']
        slides = pres_data['slidesData']
        self.assertTrue(len(slides) > 0)
        self.assertIn('data-slide-watermark="true"', slides[0]['html'],
                      'Watermark must survive presentation save and reload')

    def test_watermark_size_survives_presentation_get(self):
        """GET /api/presentations/<id> must not shrink the watermark logo.

        The read path used to run the legacy logo pass after the engine
        renumber. That pass matched the watermark overlay img (its src carries
        tenant-assets) and appended max-height:50px;width:auto, collapsing
        width:480px to a ~50px mark on every open/refresh — and the next save
        persisted the shrink."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        app_mod = self.application_module
        logo_url = '/uploads/creative/tenant-x/logo.png'
        watermarked_html = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', logo_url, width_px=480
        )
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض حجم العلامة المائية',
            'projectData': {},
            'slidesData': [{'html': watermarked_html, 'title': 'شريحة', 'type': 'content', 'is_custom': True}],
            'slideCount': 1,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        pres_id = created.get_json()['presentationId']

        fetched = client.get(f'/api/presentations/{pres_id}', headers=headers)
        self.assertEqual(fetched.status_code, 200, fetched.get_json())
        html = fetched.get_json()['presentation']['slidesData'][0]['html']
        self.assertIn('data-slide-watermark="true"', html)
        marker = html.find('slide-watermark')
        watermark_img = re.search(r'<img\b[^>]*>', html[marker:])
        self.assertIsNotNone(watermark_img, 'Watermark overlay must keep its img')
        tag = watermark_img.group(0)
        self.assertIn('width:480px', tag,
                      'Watermark width must survive a presentation GET (refresh/reopen)')
        self.assertNotIn('max-height:50px', tag,
                         'GET must not append the legacy 50px logo sizing to the watermark')
        self.assertNotIn('width:auto', tag,
                         'GET must not override the watermark width with width:auto')

    def test_watermark_explicit_opacity_is_honored_up_to_fully_opaque(self):
        """An explicit user opacity (e.g. 50%) must reach the slide, not a 12%/25% cap.

        The designer-chat loop kept counter-proposing 12% because the prompt
        capped the model there and the server clamped everything above 0.25.
        Owner rule now: explicit values pass through up to 1.0; the subtle
        default stays 0.045 for calls that omit it."""
        app_mod = self.application_module
        half = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', '/logo.png', opacity=0.5)
        self.assertIn('opacity:0.5', half)
        full = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', '/logo.png', opacity=1.0)
        self.assertIn('opacity:1.0', full)
        default = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', '/logo.png')
        self.assertIn('opacity:0.045', default)

    def test_watermark_logo_normalized_to_fixed_gray(self):
        """Every watermark renders as a flat #888888 silhouette on any surface.

        A light logo (with or without white text) vanishes on light slides, so
        the overlay filter flattens any source to mid gray with alpha preserved:
        grayscale, then to black, then inverted up to #888888."""
        app_mod = self.application_module
        white_html = ('<div class="slide" style="width:1280px;height:720px;background:#ffffff;">'
                      '<h1>محتوى</h1></div>')
        dark_html = ('<div class="slide" style="width:1280px;height:720px;background:#101828;">'
                     '<h1>محتوى</h1></div>')
        photo_html = ('<div class="slide" style="width:1280px;height:720px;'
                      "background-image:url('/uploads/cover.png');\">"
                      '<h1>محتوى</h1></div>')
        expected_filter = 'grayscale(100%) brightness(0) invert(53.3%)'

        for html in (white_html, dark_html, photo_html):
            mark = app_mod._apply_slide_watermark(html, '/logo.png')
            self.assertIn(expected_filter, mark)

        # The gray survives a model regeneration carry unchanged.
        carried = app_mod._carry_slide_watermark(
            app_mod._apply_slide_watermark(white_html, '/logo.png'), dark_html)
        self.assertIn(expected_filter, carried)

        # A mark stored with the legacy filter upgrades on renumber
        # (open/save/export) without re-applying the watermark.
        engine = self.application_module.slide_engine
        legacy_mark = app_mod._apply_slide_watermark(white_html, '/logo.png')
        legacy_mark = legacy_mark.replace(expected_filter, 'grayscale(100%)')
        renumbered = engine.renumber_presentation_slides(
            [{'html': legacy_mark, 'title': 'شريحة', 'type': 'content', 'is_custom': True}])
        self.assertIn(expected_filter, renumbered[0]['html'])

        # The preview carries the same display-time healing for draft-held slides.
        index_source = read_frontend_text()
        self.assertIn(expected_filter, index_source)

    def test_watermark_idempotent_on_repeated_normalization(self):
        """Applying the watermark twice must not duplicate the watermark element."""
        app_mod = self.application_module
        logo_url = '/uploads/creative/tenant-x/logo.png'
        html = '<div class="slide"><h1>محتوى</h1></div>'
        once = app_mod._apply_slide_watermark(html, logo_url)
        twice = app_mod._apply_slide_watermark(once, logo_url)
        self.assertEqual(once.count('data-slide-watermark="true"'), 1)
        self.assertEqual(twice.count('data-slide-watermark="true"'), 1,
                         'Applying watermark twice must not duplicate the element')

    def test_watermark_branding_column_exists_and_migrates_existing_databases(self):
        import sqlite3

        with self.app.app_context():
            columns = {row['name'] for row in db.get_db().execute('PRAGMA table_info(tenant_branding)').fetchall()}
        self.assertIn('watermark_path', columns)

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('CREATE TABLE tenant_branding (tenant_id TEXT PRIMARY KEY, lock_slide_count INTEGER DEFAULT 0)')
            db._migrate_branding_columns(conn)
            migrated = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_branding)').fetchall()}
            self.assertIn('watermark_path', migrated)
        finally:
            conn.close()

    def test_watermark_upload_is_independent_and_has_no_system_logo_fallback(self):
        from PIL import Image

        client = self.app.test_client()
        headers = self._headers(self.token_a)
        logo_path = f'/tenant-assets/{self.tenant_a}/logo'
        client.delete('/api/upload/watermark', headers=headers)
        with self.app.app_context():
            db.update_branding(self.tenant_a, logo_path=logo_path)
            db.update_branding(self.tenant_b, watermark_path=None)

        missing = client.get(f'/tenant-assets/{self.tenant_b}/watermark')
        self.assertEqual(missing.status_code, 404)

        png = io.BytesIO()
        Image.new('RGBA', (4, 4), (20, 40, 60, 128)).save(png, format='PNG')
        png.seek(0)
        uploaded = client.post('/api/upload/watermark', headers=headers, data={
            'file': (png, 'company-watermark.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(uploaded.status_code, 200, uploaded.get_json())
        branding = uploaded.get_json()['branding']
        self.assertEqual(branding['logo_path'], logo_path)
        self.assertEqual(branding['watermark_path'], f'/tenant-assets/{self.tenant_a}/watermark')
        watermark_png = Path(self.application_module.UPLOADS_DIR) / self.tenant_a / 'watermark.png'
        self.assertTrue(watermark_png.is_file())

        jpeg = io.BytesIO()
        Image.new('RGB', (4, 4), (80, 100, 120)).save(jpeg, format='JPEG')
        jpeg.seek(0)
        replaced = client.post('/api/upload/watermark', headers=headers, data={
            'file': (jpeg, 'replacement.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(replaced.status_code, 200, replaced.get_json())
        self.assertFalse(watermark_png.exists(), 'changing the extension must remove the stale source file')
        self.assertTrue((watermark_png.parent / 'watermark.jpg').is_file())

        served = client.get(f'/tenant-assets/{self.tenant_a}/watermark')
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, 'image/jpeg')
        served.close()

        deleted = client.delete('/api/upload/watermark', headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertEqual(deleted.get_json()['branding']['logo_path'], logo_path)
        self.assertIsNone(deleted.get_json()['branding']['watermark_path'])
        self.assertEqual(client.get(f'/tenant-assets/{self.tenant_a}/watermark').status_code, 404)

    def test_designer_chat_uses_uploaded_watermark_for_all_and_selected_slides(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        watermark_path = f'/tenant-assets/{self.tenant_a}/watermark'
        logo_path = f'/tenant-assets/{self.tenant_a}/logo'
        with self.app.app_context():
            db.update_branding(self.tenant_a, logo_path=logo_path, watermark_path=watermark_path)

        slides = [
            {'title': f'شريحة {number}', 'type': 'content',
             'html': f'<div class="slide"><h1>محتوى {number}</h1></div>'}
            for number in range(1, 4)
        ]
        apply_all_plan = json.dumps({
            'response': 'سأضيف العلامة المائية إلى كل الشرائح.',
            'actions': [{'tool': 'apply_watermark', 'params': {'target': 'all'}}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': apply_all_plan}}]
        }):
            applied = client.post('/api/designer-chat', headers=headers, json={
                'message': 'أظهر العلامة المائية في كل الشرائح',
                'slidesData': slides,
                'slideIndex': 0,
            })
        self.assertEqual(applied.status_code, 200, applied.get_json())
        applied_data = applied.get_json()['data']
        self.assertEqual(applied_data['actions'][0]['indexes'], [0, 1, 2])
        for slide in applied_data['slidesData']:
            spec = self.application_module._watermark_spec_from_html(slide['html'])
            self.assertIsNotNone(spec)
            self.assertEqual(spec['logo_url'], watermark_path)

        remove_selected_plan = json.dumps({
            'response': 'سأخفي العلامة المائية من الشريحة الثانية.',
            'actions': [{'tool': 'remove_watermark', 'params': {
                'target': 'indexes', 'indexes': [2],
            }}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': remove_selected_plan}}]
        }):
            removed = client.post('/api/designer-chat', headers=headers, json={
                'message': 'اخف العلامة المائية من الشريحة 2',
                'slidesData': applied_data['slidesData'],
                'slideIndex': 0,
            })
        self.assertEqual(removed.status_code, 200, removed.get_json())
        removed_slides = removed.get_json()['data']['slidesData']
        self.assertTrue(self.application_module._is_watermark_visible(removed_slides[0]['html']))
        # Hiding keeps the layer with its geometry so a later show restores it.
        hidden_spec = self.application_module._watermark_spec_from_html(removed_slides[1]['html'])
        self.assertIsNotNone(hidden_spec)
        self.assertFalse(hidden_spec['visible'])
        self.assertTrue(self.application_module._is_watermark_visible(removed_slides[2]['html']))

        apply_selected_plan = json.dumps({
            'response': 'سأضيف العلامة المائية إلى الشرائح المحددة.',
            'actions': [{'tool': 'apply_watermark', 'params': {
                'target': 'indexes', 'indexes': [1, 3],
            }}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': apply_selected_plan}}]
        }):
            selected = client.post('/api/designer-chat', headers=headers, json={
                'message': 'أظهر العلامة المائية في الشرائح 1 و3',
                'slidesData': slides,
                'slideIndex': 1,
            })
        selected_slides = selected.get_json()['data']['slidesData']
        self.assertIsNotNone(self.application_module._watermark_spec_from_html(selected_slides[0]['html']))
        self.assertIsNone(self.application_module._watermark_spec_from_html(selected_slides[1]['html']))
        self.assertIsNotNone(self.application_module._watermark_spec_from_html(selected_slides[2]['html']))

    def test_designer_chat_does_not_fall_back_to_logo_when_watermark_is_missing(self):
        client = self.app.test_client()
        with self.app.app_context():
            db.update_branding(
                self.tenant_a,
                logo_path=f'/tenant-assets/{self.tenant_a}/logo',
                watermark_path=None,
            )
        plan = json.dumps({
            'response': 'سأضيف العلامة المائية.',
            'actions': [{'tool': 'apply_watermark', 'params': {'target': 'current'}}],
        }, ensure_ascii=False)
        slide = {'title': 'شريحة', 'type': 'content', 'html': '<div class="slide"><h1>محتوى</h1></div>'}
        with patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': plan}}]
        }):
            response = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                'message': 'أظهر العلامة المائية', 'slidesData': [slide], 'slideIndex': 0,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()['data']
        self.assertEqual(data['failureReason'], 'watermark_missing')
        self.assertEqual(data['actions'][0]['status'], 'failed')
        self.assertNotIn('data-slide-watermark="true"', data['slidesData'][0]['html'])

    def test_manual_slide_watermark_control_tracks_html_and_edit_history(self):
        index_source = read_frontend_text()
        self.assertIn('id="settingsWatermarkPreview"', index_source)
        self.assertIn('id="watermarkFileInput"', index_source)
        self.assertIn("api('POST', '/api/upload/watermark', form, true)", index_source)
        self.assertIn("api('DELETE', '/api/upload/watermark')", index_source)
        self.assertIn("showLoader('رفع العلامة المائية'", index_source)
        self.assertIn('setWatermarkSettingsBusy(true);', index_source)

        toolbar = index_source.split('function slideEditToolbarHTML(index)', 1)[1]
        toolbar = toolbar.split('\n    function normalizeHexColor', 1)[0]
        self.assertIn('data-slide-edit-watermark="toggle"', toolbar)
        self.assertIn('إظهار العلامة المائية', toolbar)
        self.assertIn('isWatermarkVisible(tenantSlidesData[index]', toolbar)

        toggle = index_source.split('function setSlideWatermarkVisibility(index, visible)', 1)[1]
        toggle = toggle.split('\n    function deckWatermarkMarkup', 1)[0]
        self.assertIn('tenantBranding.watermark_path', toggle)
        self.assertIn('pushSlideEditHistory(index)', toggle)
        self.assertIn('setHtmlWatermarkVisible(slide.html', toggle)
        self.assertIn('isWatermarkVisible(slide.html)', toggle)
        self.assertIn('لم تُرفع علامة مائية للشركة', toggle)
        self.assertIn('slide._designer_keep_html = true;', toggle)
        self.assertIn('slide.is_custom = true;', toggle)
        self.assertIn('touchSlideEditSession(index);', toggle)
        self.assertIn('tenantProjectData.tenantSlidesData = tenantSlidesData;', toggle)
        self.assertIn('triggerAutoSaveDraft();', toggle)
        self.assertIn('refreshSingleSlideCard(index);', toggle)

        engine = self.application_module.slide_engine
        watermark_path = f'/tenant-assets/{self.tenant_a}/watermark'
        html = self.application_module._apply_slide_watermark(
            '<div class="slide"><h1>محتوى</h1></div>', watermark_path)
        resolved = engine.resolve_logo_in_html(
            html, self.tenant_a,
            _branding_cache={'logo_path': f'/tenant-assets/{self.tenant_a}/logo'},
        )
        self.assertEqual(self.application_module._watermark_spec_from_html(resolved)['logo_url'], watermark_path)

    def test_watermark_upload_rejects_svg_fake_and_oversized_images(self):
        from PIL import Image

        client = self.app.test_client()
        headers = self._headers(self.token_a)
        client.delete('/api/upload/watermark', headers=headers)

        svg = client.post('/api/upload/watermark', headers=headers, data={
            'file': (io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'), 'mark.svg'),
        }, content_type='multipart/form-data')
        self.assertEqual(svg.status_code, 400)

        fake = client.post('/api/upload/watermark', headers=headers, data={
            'file': (io.BytesIO(b'%PDF-1.4 not an image'), 'mark.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(fake.status_code, 400)

        big_png = io.BytesIO()
        Image.new('RGB', (8, 8), (10, 20, 30)).save(big_png, format='PNG')
        big_payload = big_png.getvalue() + b'\x00' * (6 * 1024 * 1024)
        too_big = client.post('/api/upload/watermark', headers=headers, data={
            'file': (io.BytesIO(big_payload), 'mark.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(too_big.status_code, 400)

        with self.app.app_context():
            self.assertIsNone((db.get_branding(self.tenant_a) or {}).get('watermark_path'))

    def test_watermark_branding_put_cannot_set_client_path(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        with self.app.app_context():
            db.update_branding(self.tenant_a, watermark_path=None)
        response = client.put('/api/branding', headers=headers, json={
            'watermark_path': '/etc/passwd',
            'company_name': 'شركة الاختبار',
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            branding = db.get_branding(self.tenant_a) or {}
        self.assertNotEqual(branding.get('watermark_path'), '/etc/passwd')
        self.assertEqual(branding.get('company_name'), 'شركة الاختبار')

    def test_watermark_hide_preserves_geometry_and_legacy_counts_as_visible(self):
        app_mod = self.application_module
        base = '<div class="slide"><h1>محتوى</h1></div>'
        watermark_url = f'/tenant-assets/{self.tenant_a}/watermark'
        shown = app_mod._apply_slide_watermark(base, watermark_url, opacity=0.2, width_px=600)
        # Simulate a user move: the logo img carries a manual translate.
        moved = shown.replace('width:600px;', 'width:600px;transform:translate(40px, 30px);')
        hidden = app_mod._set_slide_watermark_visible(moved, False)
        spec = app_mod._watermark_spec_from_html(hidden)
        self.assertIsNotNone(spec)
        self.assertFalse(spec['visible'])
        self.assertIn('translate(40px, 30px)', hidden)
        self.assertIn('width:600px', hidden)
        reshown = app_mod._set_slide_watermark_visible(hidden, True)
        respec = app_mod._watermark_spec_from_html(reshown)
        self.assertTrue(respec['visible'])
        self.assertIn('translate(40px, 30px)', reshown)
        self.assertIn('opacity:0.2', reshown)

        legacy = ('<div class="slide-watermark" data-slide-watermark="true" aria-hidden="true" '
                  'style="position:absolute;inset:0;display:flex;opacity:0.045;">'
                  '<img src="/tenant-assets/t/watermark"></div>')
        self.assertTrue(app_mod._watermark_spec_from_html(legacy)['visible'])
        self.assertTrue(app_mod._is_watermark_visible(legacy))

        # Re-applying a visible mark keeps the user geometry instead of resetting it.
        kept = app_mod._apply_slide_watermark(moved, watermark_url, opacity=0.045, width_px=480)
        self.assertIn('translate(40px, 30px)', kept)
        self.assertIn('opacity:0.2', kept)

    def test_watermark_carry_copies_layer_verbatim_and_keeps_hidden(self):
        app_mod = self.application_module
        watermark_url = f'/tenant-assets/{self.tenant_a}/watermark'
        source = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>قديم</h1></div>', watermark_url, opacity=0.3, width_px=600)
        source = source.replace('width:600px;', 'width:600px;transform:translate(25px, 10px);')
        carried = app_mod._carry_slide_watermark(source, '<div class="slide"><h1>جديد</h1></div>')
        self.assertIn('translate(25px, 10px)', carried)
        self.assertIn('opacity:0.3', carried)
        self.assertIn(watermark_url, carried)

        hidden_source = app_mod._set_slide_watermark_visible(source, False)
        carried_hidden = app_mod._carry_slide_watermark(
            hidden_source, '<div class="slide"><h1>جديد</h1></div>')
        self.assertFalse(app_mod._is_watermark_visible(carried_hidden))
        self.assertIn('translate(25px, 10px)', carried_hidden)

    def test_watermark_reapply_repoints_stale_source_without_losing_geometry(self):
        app_mod = self.application_module
        old_src = f'/tenant-assets/{self.tenant_a}/logo'
        new_src = f'/tenant-assets/{self.tenant_a}/watermark'
        base = '<div class="slide"><h1>محتوى</h1></div>'
        old_layer = app_mod._apply_slide_watermark(base, old_src, opacity=0.2, width_px=600)
        old_layer = old_layer.replace('width:600px;', 'width:600px;transform:translate(40px, 30px);')
        refreshed = app_mod._apply_slide_watermark(old_layer, new_src)
        self.assertIn(new_src, refreshed)
        self.assertNotIn(old_src, refreshed)
        self.assertIn('translate(40px, 30px)', refreshed)
        self.assertIn('opacity:0.2', refreshed)
        self.assertEqual(refreshed.count('data-slide-watermark'), 1)

        hidden_old = app_mod._set_slide_watermark_visible(old_layer, False)
        reshown = app_mod._set_slide_watermark_visible(hidden_old, True, new_src)
        self.assertTrue(app_mod._is_watermark_visible(reshown))
        self.assertIn(new_src, reshown)
        self.assertIn('translate(40px, 30px)', reshown)

        index_source = read_frontend_text()
        self.assertIn('function refreshWatermarkSrc(html, newUrl)', index_source)

    def test_watermark_deterministic_verbs_scope_and_no_size_up_on_show(self):
        app_mod = self.application_module
        slides = [
            {'title': 'شريحة 1', 'type': 'content', 'html': '<div class="slide"><h1>واحد</h1></div>'},
            {'title': 'شريحة 2', 'type': 'content', 'html': '<div class="slide"><h1>اثنان</h1></div>'},
        ]
        hide_plan = app_mod._designer_deterministic_plan('اخفي العلامة المائية من الشريحة 2', slides, 0, [1])
        self.assertEqual(hide_plan['actions'][0]['tool'], 'remove_watermark')
        self.assertEqual(hide_plan['actions'][0]['params']['target'], 'indexes')

        disable_plan = app_mod._designer_deterministic_plan('عطّل العلامة المائية', slides, 0, [])
        self.assertEqual(disable_plan['actions'][0]['tool'], 'remove_watermark')
        self.assertEqual(disable_plan['actions'][0]['params']['target'], 'current')

        show_plan = app_mod._designer_deterministic_plan('أظهر العلامة المائية', slides, 0, [])
        self.assertEqual(show_plan['actions'][0]['tool'], 'apply_watermark')
        self.assertEqual(show_plan['actions'][0]['params']['target'], 'current')
        # «إظهار» is visibility only, never an implicit enlarge.
        self.assertEqual(show_plan['actions'][0]['params']['opacity'], 0.045)
        self.assertEqual(show_plan['actions'][0]['params']['width_px'], 480)

        bigger_plan = app_mod._designer_deterministic_plan('اجعل العلامة المائية أكبر', slides, 0, [])
        self.assertEqual(bigger_plan['actions'][0]['params']['width_px'], 640)

    def test_watermark_change_log_names_show_hide_per_slide(self):
        import change_tracking

        old = [{'title': 'شريحة 1', 'html': '<div class="slide"><h1>نص</h1></div>'}]
        shown_html = self.application_module._apply_slide_watermark(
            old[0]['html'], f'/tenant-assets/{self.tenant_a}/watermark')
        lines = change_tracking.describe_slide_changes(old, [{'title': 'شريحة 1', 'html': shown_html}])
        self.assertTrue(any('العلامة المائية' in line and 'أُظهرت' in line for line in lines),
                        lines)
        hidden_html = self.application_module._set_slide_watermark_visible(shown_html, False)
        hide_lines = change_tracking.describe_slide_changes(
            [{'title': 'شريحة 1', 'html': shown_html}], [{'title': 'شريحة 1', 'html': hidden_html}])
        self.assertTrue(any('أُخفيت' in line for line in hide_lines), hide_lines)
        # The watermark img itself must not also count as a generic photo change.
        self.assertFalse(any(line.endswith('إلى 1') and 'الصور' in line for line in lines), lines)

    def test_watermark_hidden_layers_stay_out_of_exports(self):
        from exports import pptx_export
        from generate_pdf_from_preview import _strip_hidden_watermark_overlays

        app_mod = self.application_module
        watermark_url = f'/tenant-assets/{self.tenant_a}/watermark'
        visible = app_mod._apply_slide_watermark(
            '<div class="slide"><h1>نص</h1></div>', watermark_url)
        hidden = app_mod._set_slide_watermark_visible(visible, False)
        self.assertIn('data-slide-watermark', _strip_hidden_watermark_overlays(visible))
        self.assertNotIn('data-slide-watermark', _strip_hidden_watermark_overlays(hidden))
        prepared_hidden = pptx_export._prepare_slide_html(hidden, self.tenant_a)
        self.assertNotIn('data-slide-watermark', prepared_hidden)
        prepared_visible = pptx_export._prepare_slide_html(visible, self.tenant_a)
        self.assertIn('data-slide-watermark', prepared_visible)

    def test_presentation_sync_failure_is_reported_not_swallowed(self):
        """saveProjectAsDraftNow must report a presentation PUT failure instead of
        silently claiming full success. The JS must not mark the draft clean on failure."""
        index_source = read_frontend_text()
        save_body = index_source.split('async function saveProjectAsDraftNow(', 1)[1]
        save_body = save_body.split('\n    async function ', 1)[0]
        # The snapshot is taken before the async save so both records see the same data.
        self.assertIn('const snapshot = JSON.parse(JSON.stringify(data));', save_body)
        # The presentation PUT response is checked for success.
        self.assertIn("if (!presResp?.success) throw new Error(presResp?.error || 'تعذر حفظ العرض');", save_body)
        # On failure the dirty flag is set again (not cleared).
        self.assertIn('setDraftDirty(true);', save_body)
        # The draft is only marked clean after both saves succeed.
        self.assertIn('tenantDraftDirty = false;', save_body)
        # The success block comes after the presentation sync block.
        self.assertGreater(save_body.index('tenantDraftDirty = false;'),
                           save_body.index("if (!presResp?.success)"))

    def test_extract_listing_prices_reads_arabic_english_and_jsonld(self):
        """The fetched page's own markup carries the figure the search excerpt
        dropped — Arabic ريال, SAR, and JSON-LD prices all count."""
        module = self.application_module
        html = (
            '<html><body>إيجار سنوي 18,000 ريال سنوياً للمحل '
            + ('x' * 220) +
            '<span>SAR 45,000</span> شهريا '
            '<script type="application/ld+json">{"offers":{"price":95000}}</script>'
            '</body></html>')
        prices = module._extract_listing_prices(html)
        values = {item['value'] for item in prices}
        self.assertIn(18000.0, values)
        self.assertIn(45000.0, values)
        self.assertIn(95000.0, values)
        annual = [item for item in prices if item['value'] == 18000.0]
        self.assertEqual(annual[0]['period'], 'سنوي')
        monthly = [item for item in prices if item['value'] == 45000.0]
        self.assertEqual(monthly[0]['period'], 'شهري')

    def test_fill_competitor_price_from_listings_sets_median_and_marks_estimated(self):
        """Empty price fields get the median of grounded listing mentions, a
        «متوسط» type, source attribution and the estimated marker."""
        module = self.application_module
        pages = {
            'https://bayut.sa/listing-a': 'مكاتب إدارية 18,000 ريال سنوياً',
            'https://bayut.sa/listing-b': 'محل تجاري بإيجار 24,000 ريال سنوياً',
            'https://bayut.sa/listing-c': 'مساحات 36,000 ريال سنوياً',
        }
        row = {'name': 'مجمع تجريبي', 'operation_type': 'إيجار',
               'source_urls': list(pages)}
        with patch.object(module, '_read_market_source_page',
                          side_effect=lambda url, **kw: (pages.get(url, ''), '')):
            filled = module._fill_competitor_price_from_listings(row, list(pages))
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '24000')
        self.assertEqual(row['price_type'], 'متوسط إيجار الوحدة')
        self.assertTrue(row['price_listed'])
        self.assertIn('متوسط إعلانات', row['note'])
        field_sources = row['field_sources']['price_value']
        self.assertEqual(set(field_sources), set(pages))

    def test_fill_competitor_price_skips_dead_urls_and_single_mention_typing(self):
        module = self.application_module
        row = {'name': 'مشروع', 'operation_type': 'إيجار',
               'dead_source_urls': ['https://dead.example/x'],
               'source_urls': ['https://dead.example/x', 'https://bayut.sa/only']}
        pages = {'https://bayut.sa/only': 'إيجار 30,000 ريال شهرياً'}
        fetched = []
        with patch.object(module, '_read_market_source_page',
                          side_effect=lambda url, **kw: (fetched.append(url), (pages.get(url, ''), ''))[1]):
            filled = module._fill_competitor_price_from_listings(row, row['source_urls'])
        self.assertTrue(filled)
        self.assertEqual(fetched, ['https://bayut.sa/only'])
        self.assertEqual(row['price_type'], 'إيجار الوحدة الشهري')
        self.assertEqual(row['price_value'], '30000')

    def test_fill_competitor_price_uses_citation_content_before_fetching(self):
        """The search provider's excerpt already carries the figure for pages
        the direct fetch cannot reach (bayut answers 401 to the pinned GET) —
        the citation content is searched first and the page is never fetched."""
        module = self.application_module
        pages = [{'url': 'https://bayut.sa/listing-401',
                  'title': 'محل للإيجار',
                  'content': 'محل تجاري للإيجار 18,000 ريال سنوياً في حي الرحاب'}]
        row = {'name': 'مجمع الرحاب', 'operation_type': 'إيجار',
               'source_urls': ['https://bayut.sa/listing-401']}
        with patch.object(module, '_read_market_source_page',
                          side_effect=AssertionError('must not fetch — the excerpt has the price')):
            filled = module._fill_competitor_price_from_listings(
                row, ['https://bayut.sa/listing-401'], pages=pages)
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '18000')
        self.assertEqual(row['price_type'], 'إيجار الوحدة السنوي')
        self.assertTrue(row['price_listed'])

    def test_market_url_alive_keeps_probe_failures_and_drops_only_proven_dead(self):
        """The search provider retrieved the page once, so a slow bot wall
        (Cloudflare holds the socket until the probe times out) is not a dead
        link. Only 404/410 and DNS failure count as proof."""
        import socket as _socket
        module = self.application_module

        class _Resp:
            def __init__(self, status):
                self.status_code = status
            def close(self):
                pass

        url = 'https://wasalt.sa/property/rent/1'
        with patch.object(module, '_public_host_addresses', return_value=('1.2.3.4',)):
            with patch.object(module.requests, 'head',
                              side_effect=module.requests.ReadTimeout('t')), \
                 patch.object(module.requests, 'get',
                              side_effect=module.requests.ConnectTimeout('t')):
                self.assertTrue(module._market_url_alive(url))
            with patch.object(module.requests, 'head', return_value=_Resp(403)):
                self.assertTrue(module._market_url_alive(url))
            # A HEAD-only 404 is a server quirk, not proof — the GET decides.
            with patch.object(module.requests, 'head', return_value=_Resp(404)), \
                 patch.object(module.requests, 'get', return_value=_Resp(200)):
                self.assertTrue(module._market_url_alive(url))
            with patch.object(module.requests, 'head', return_value=_Resp(404)), \
                 patch.object(module.requests, 'get', return_value=_Resp(404)):
                self.assertFalse(module._market_url_alive(url))
            dns_err = module.requests.ConnectionError('nxdomain')
            dns_err.__cause__ = _socket.gaierror(-2, 'Name or service not known')
            with patch.object(module.requests, 'head', side_effect=dns_err):
                self.assertFalse(module._market_url_alive(url))

    def test_import_competitor_listing_photo_stores_og_image(self):
        """A portal-only competitor with no official site gets the listing
        page's own og:image — marked as a listing photo, never a portal logo."""
        module = self.application_module
        html = ('<html><head>'
                '<meta property="og:image" content="https://images.bayut.com/thumb/prop-123.jpg">'
                '<meta property="og:image" content="https://portal.example/logo-share.png">'
                '</head></html>')
        row = {'id': 'c1', 'name': 'مجمع', 'source_urls': ['https://bayut.sa/listing-1']}
        downloaded = []
        with patch.object(module, '_read_market_source_page',
                          return_value=(html, '')), \
                patch.object(module, '_download_listing_image',
                             side_effect=lambda url: (downloaded.append(url),
                                                      (b'PNGDATA', 'image/jpeg', '.jpg')
                                                      if 'prop-123' in url else (None, None, None))[1]), \
                patch.object(module, '_store_project_upload',
                             return_value={'id': 'stored-photo-1'}), \
                patch.object(module, '_publish_project_file_as_creative_image',
                             return_value='/api/project-files/stored-photo-1'):
            module._import_competitor_listing_photo(row, draft_id='d1')
        self.assertEqual(row['logo_file_id'], 'stored-photo-1')
        self.assertTrue(row['logo_listing_photo'])
        self.assertEqual(row['logo_source_url'], 'https://bayut.sa/listing-1')
        self.assertEqual(downloaded, ['https://images.bayut.com/thumb/prop-123.jpg'])
        self.assertIn('https://bayut.sa/listing-1', row['field_sources']['logo_url'])

    def test_download_listing_image_rejects_portal_brand_assets(self):
        """logo/brand/share asset URLs must never become the competitor image."""
        module = self.application_module
        for url in ('https://portal.example/assets/logo.png',
                    'https://portal.example/img/brand-mark.jpg',
                    'https://portal.example/share-banner.webp',
                    'http://portal.example/insecure.jpg'):
            self.assertEqual(module._download_listing_image(url), (None, None, None))

    def test_market_competitors_chunked_into_balanced_slides(self):
        """At most 4 competitors per slide, split evenly: 6 become 3+3, 9 become 3+3+3."""
        engine = self.application_module.slide_engine

        def plan_for(count):
            competitors = [
                {'id': f'c{i}', 'name': f'منافس {i}', 'price': 1000 * i, 'price_type': 'سعر المتر', 'status': 'قائم'}
                for i in range(1, count + 1)
            ]
            draft = {
                'project_name': 'مشروع الاختبار',
                'city': 'الرياض',
                'market_study_data': json.dumps({'competitors': competitors}, ensure_ascii=False),
            }
            plan = engine.normalize_presentation_plan({}, project_data=draft, images={})
            market_slides = [s for s in plan['slides'] if s.get('section_key') == 'market']
            return draft, [s for s in market_slides if 'competitors' in str(s.get('content_source') or '')]

        _draft4, comp_slides4 = plan_for(4)
        self.assertEqual(len(comp_slides4), 1)
        self.assertEqual((comp_slides4[0]['competitor_start'], comp_slides4[0]['competitor_end']), (0, 4))

        _draft9, comp_slides9 = plan_for(9)
        self.assertEqual(
            [(s['competitor_start'], s['competitor_end']) for s in comp_slides9],
            [(0, 3), (3, 6), (6, 9)])

        draft6, comp_slides = plan_for(6)
        self.assertEqual(len(comp_slides), 2)
        self.assertEqual(comp_slides[0]['competitor_start'], 0)
        self.assertEqual(comp_slides[0]['competitor_end'], 3)
        self.assertIn('(1/2)', comp_slides[0]['title'])
        self.assertEqual(comp_slides[1]['competitor_start'], 3)
        self.assertEqual(comp_slides[1]['competitor_end'], 6)
        self.assertIn('(2/2)', comp_slides[1]['title'])

        # Verify rendering of slide 1 contains only the first 3 competitors
        html_1 = engine._build_structured_fallback_slide(comp_slides[0], draft6, {})
        for index in range(1, 4):
            self.assertIn(f'منافس {index}', html_1)
        for index in range(4, 7):
            self.assertNotIn(f'منافس {index}', html_1)

        # Verify rendering of slide 2 contains only the remaining 3 competitors
        html_2 = engine._build_structured_fallback_slide(comp_slides[1], draft6, {})
        for index in range(1, 4):
            self.assertNotIn(f'منافس {index}', html_2)
        for index in range(4, 7):
            self.assertIn(f'منافس {index}', html_2)

    def test_executive_content_multi_slide_planning_and_rendering(self):
        """Executive content with opportunity, features and summary must yield 3 slides."""
        engine = self.application_module.slide_engine
        exec_content = {
            'opportunity': 'تمثل هذه الأرض فرصة استثمارية نادرة بفضل موقعها المباشر على المحور الرئيسي.',
            'features': ['موقع استراتيجي على طريق الملك فهد', 'كثافة مرورية وتدفقات تجارية عالية', 'عائد استثماري مستهدف يفوق 14%'],
            'summary': 'ملخص تنفيذي شامل يوضح معالم المشروع وجدواه الاستثمارية ومحددات التطوير.',
        }
        draft = {
            'project_name': 'مشروع الروابي',
            'city': 'الرياض',
            'district': 'الصحافة',
            'project_type': 'تجاري مكتبي',
            'executive_content': json.dumps(exec_content, ensure_ascii=False),
        }
        plan = engine.normalize_presentation_plan({}, project_data=draft, images={})
        exec_slides = [s for s in plan['slides'] if s.get('section_key') == 'executive_summary' and s.get('type') == 'content']
        self.assertEqual(len(exec_slides), 3)

        sources = [s.get('content_source') for s in exec_slides]
        self.assertEqual(sources, [
            'executive_content.opportunity',
            'executive_content.features',
            'executive_content.summary',
        ])

        # Render opportunity slide
        opp_html = engine._build_structured_fallback_slide(exec_slides[0], draft, {})
        self.assertIn('الفرصة الاستثمارية', opp_html)
        self.assertIn('تمثل هذه الأرض فرصة استثمارية', opp_html)

        # Render features slide
        feat_html = engine._build_structured_fallback_slide(exec_slides[1], draft, {})
        self.assertIn('المميزات وفرص الاستثمار', feat_html)
        self.assertIn('01', feat_html)
        self.assertIn('موقع استراتيجي', feat_html)

        # Render summary slide
        sum_html = engine._build_structured_fallback_slide(exec_slides[2], draft, {})
        self.assertIn('الملخص التنفيذي', sum_html)
        self.assertIn('ملخص تنفيذي شامل', sum_html)

    def test_executive_summary_parses_sections_and_paginates_by_volume(self):
        """The long labelled executive summary splits into labelled sections and
        content-height pages instead of one unreadable slide."""
        engine = self.application_module.slide_engine
        block = 'نص معتمد مفصل يغطي هذا القسم بالكامل مع أرقام ومؤشرات وإسقاطات مالية. ' * 14
        summary = '\n\n'.join(
            f'{label}\n\n{block}' for label in (
                'البيانات الأساسية', 'الموقع', 'الأرض والاشتراطات', 'الجدول الزمني',
                'الدراسة المالية', 'فريق العمل', 'دراسة السوق', 'الخلاصة'))
        draft = {'project_name': 'مشروع', 'executive_content': json.dumps(
            {'summary': summary}, ensure_ascii=False)}

        sections = engine._executive_summary_sections(draft)
        self.assertEqual(len(sections), 8)
        self.assertEqual([label for label, _text in sections][0], 'البيانات الأساسية')
        self.assertEqual(sections[-1][0], 'الخلاصة')

        pages = engine._executive_summary_pages(draft)
        self.assertGreaterEqual(len(pages), 2)
        self.assertEqual(sum(len(rows) for _start, rows in pages), 8)
        starts = [start for start, _rows in pages]
        self.assertEqual(starts[0], 0)
        self.assertTrue(all(starts[i] < starts[i + 1] for i in range(len(starts) - 1)))

        plan = engine.normalize_presentation_plan({}, project_data=draft, images={})
        summary_slides = [s for s in plan['slides']
                          if str(s.get('content_source') or '').startswith('executive_content.summary')]
        self.assertEqual(len(summary_slides), len(pages))
        self.assertEqual(summary_slides[0].get('content_source'), 'executive_content.summary')
        self.assertEqual(summary_slides[0].get('market_row_start'), pages[0][0])
        self.assertEqual(summary_slides[0].get('market_row_end'), pages[0][0] + len(pages[0][1]))
        for slide, (start, rows) in zip(summary_slides[1:], pages[1:]):
            self.assertEqual(slide.get('content_source'),
                             f'executive_content.summary:{start}:{start + len(rows)}')
        self.assertIn('(1/', str(summary_slides[0].get('title') or ''))
        # Executive content is a text-only SOL section: no image or map tokens
        # are ever reserved on its slides.
        for slide in summary_slides:
            self.assertEqual(slide.get('image_tokens') or [], [])
            self.assertFalse(slide.get('requires_image'))
            self.assertEqual(slide.get('design_style'), 'editorial')
        # Page 1 keeps the plain source, so the data note must slice by the
        # explicit row range instead of handing SOL the whole document.
        note = engine._slide_source_data_note(summary_slides[0], draft)
        self.assertIn('البيانات الأساسية', note)
        self.assertNotIn('الخلاصة', note)
        # Executive slides are designed by SOL, not the fixed renderer.
        self.assertIn('حرية كاملة في ابتكار تكوين تحريري',
                      engine.build_slide_user_msg(summary_slides[0], 1, len(plan['slides']), {}, draft))

        first_html = engine._build_structured_fallback_slide(summary_slides[0], draft, {})
        self.assertIn('البيانات الأساسية', first_html)
        self.assertNotIn('المعتمد دون إضافة أو تكرار', first_html)
        last_html = engine._build_structured_fallback_slide(summary_slides[-1], draft, {})
        self.assertIn('الخلاصة', last_html)
        self.assertNotIn('المعتمد دون إضافة أو تكرار', last_html)
        # Section numbering continues across pages instead of restarting at 01.
        last_start = pages[-1][0]
        self.assertIn(f'{last_start + 1:02d}', last_html)

    def test_executive_opportunity_chunks_text_and_features_split_dash_items(self):
        engine = self.application_module.slide_engine
        opportunity = ' '.join(
            f'الجملة المعتمدة رقم {i} تصف جانباً استثمارياً فريداً للمشروع بإسهاب.'
            for i in range(30))
        features = 'موقع استراتيجي على الكورنيش - إطلالة بحرية مباشرة - فندق 5 نجوم وسكن فاخر - عائد مستهدف 14%'
        draft = {'project_name': 'مشروع', 'executive_content': json.dumps(
            {'opportunity': opportunity, 'features': features}, ensure_ascii=False)}

        items = engine._executive_feature_items(draft)
        self.assertEqual(len(items), 4)
        self.assertEqual(items[2], 'فندق 5 نجوم وسكن فاخر')

        chunks = engine._exec_text_chunks(opportunity)
        self.assertGreater(len(chunks), 1)

        opp_html = engine._build_structured_fallback_slide(
            {'title': 'الفرصة الاستثمارية', 'content_source': 'executive_content.opportunity',
             'type': 'content', 'image_tokens': []}, draft, {})
        self.assertIn('الجملة المعتمدة رقم', re.sub(r'<[^>]+>', '', opp_html))
        self.assertNotIn('المعتمدة دون إضافة أو تكرار', opp_html)
        self.assertGreaterEqual(opp_html.count('data-exec-topic'), 1)

        feat_html = engine._build_structured_fallback_slide(
            {'title': 'المميزات وفرص الاستثمار', 'content_source': 'executive_content.features',
             'type': 'content', 'image_tokens': []}, draft, {})
        feat_text = re.sub(r'<[^>]+>', '', feat_html)
        for item in items:
            self.assertIn(item, feat_text)
        self.assertIn('04', feat_html)
        self.assertIn('4 ميزة تنافسية', feat_html)

        # A ranged opportunity slide feeds SOL only its slice, not the whole text.
        ranged_note = engine._slide_source_data_note(
            {'content_source': 'executive_content.opportunity:0:1',
             'market_row_start': 0, 'market_row_end': 1}, draft)
        self.assertIn(chunks[0][:40], ranged_note)
        self.assertNotIn('رقم 29', ranged_note)

    def test_normalized_plan_carries_engine_version_for_checkpoint_safety(self):
        engine = self.application_module.slide_engine
        draft = {'project_name': 'مشروع', 'executive_content': json.dumps(
            {'summary': 'الملخص التنفيذي\n\nالموقع\n\nنص معتمد للموقع يفيض عن الحد.'},
            ensure_ascii=False)}
        plan = engine.normalize_presentation_plan(
            {'slides': [{'title': 'الملخص التنفيذي', 'type': 'content',
                         'section_key': 'executive_summary'}]}, draft, {})
        self.assertTrue(engine.SLIDE_ENGINE_VERSION)
        self.assertEqual(plan.get('engine_version'), engine.SLIDE_ENGINE_VERSION)
        filtered = engine.filter_presentation_plan_sections(plan, ('executive_summary',))
        self.assertEqual(filtered.get('engine_version'), engine.SLIDE_ENGINE_VERSION)

    def test_stray_executive_source_slides_are_removed_from_other_groups(self):
        """A stray slide carrying executive_content.* outside the executive
        section used to be planned whole-document and rendered as one dense
        slide. Plan normalization now removes it and rebuilds canonical paged
        executive slides instead."""
        engine = self.application_module.slide_engine
        draft = self._multi_page_executive_draft()
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'شريحة ضالة بالملخص كله', 'type': 'content', 'section_key': 'closing',
             'content_source': 'executive_content.summary'},
            {'title': 'شريحة ضالة بالفرصة', 'type': 'content', 'section_key': 'market',
             'content_source': 'executive_content.opportunity'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, draft, {})
        exec_slides = [s for s in plan['slides']
                       if str(s.get('content_source') or '').startswith('executive_content.')]
        self.assertTrue(exec_slides)
        for slide in exec_slides:
            self.assertEqual(slide.get('section_key'), 'executive_summary', slide.get('title'))
            self.assertIsNotNone(slide.get('market_row_start'), slide.get('title'))
            self.assertIsNotNone(slide.get('market_row_end'), slide.get('title'))
        titles = [s.get('title') for s in exec_slides]
        self.assertNotIn('شريحة ضالة بالملخص كله', titles)
        self.assertNotIn('شريحة ضالة بالفرصة', titles)

    def test_unscoped_executive_sources_fall_back_to_first_page(self):
        """executive_content.* without a page range or row metadata must scope
        to the first page only — never the entire document on one slide."""
        engine = self.application_module.slide_engine
        draft = self._multi_page_executive_draft()
        summary_pages = engine._executive_summary_pages(draft)
        self.assertGreaterEqual(len(summary_pages), 2)

        stray = {'content_source': 'executive_content.summary', 'type': 'content'}
        note = engine._slide_source_data_note(stray, draft)
        first_labels = [label or text[:20] for label, text in summary_pages[0][1]]
        self.assertIn(first_labels[0], note)
        last_label = summary_pages[-1][1][-1][0]
        if last_label:
            self.assertNotIn(last_label, note)
        texts = engine._required_slide_texts(stray, draft)
        self.assertEqual(len(texts), len(summary_pages[0][1]))

        opp_slide = {'content_source': 'executive_content.opportunity', 'type': 'content'}
        chunks = engine._exec_text_chunks(
            json.loads(draft['executive_content'])['opportunity'])
        opp_pages = engine._budget_row_pages([('', c) for c in chunks])
        self.assertGreaterEqual(len(opp_pages), 2)
        last_page_head = opp_pages[-1][1][0][1][:40]
        opp_note = engine._slide_source_data_note(opp_slide, draft)
        self.assertIn(chunks[0][:40], opp_note)
        self.assertNotIn(last_page_head, opp_note)
        opp_texts = engine._required_slide_texts(opp_slide, draft)
        self.assertEqual(opp_texts, [c for _l, c in opp_pages[0][1]])

        feat_slide = {'content_source': 'executive_content.features', 'type': 'content'}
        feat_texts = engine._required_slide_texts(feat_slide, draft)
        items = engine._executive_feature_items(draft)
        self.assertLess(len(feat_texts), len(items))
        self.assertEqual(feat_texts, items[:len(feat_texts)])

        opp_html = engine._build_structured_fallback_slide(opp_slide, draft, {})
        self.assertIn('الجملة المعتمدة رقم 0', re.sub(r'<[^>]+>', '', opp_html))
        self.assertNotIn(last_page_head, re.sub(r'<[^>]+>', '', opp_html))
        feat_html = engine._build_structured_fallback_slide(feat_slide, draft, {})
        feat_text = re.sub(r'<[^>]+>', '', feat_html)
        self.assertIn(items[0], feat_text)
        self.assertNotIn(items[-1], feat_text)
