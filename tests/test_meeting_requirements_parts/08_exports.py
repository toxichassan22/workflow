class MeetingRequirementsTestsPart07(MeetingRequirementsTests):

    def test_refresh_slide_map_sources_repoints_stale_frozen_url(self):
        module = self.application_module
        old_path, _marks = self._persisted_map_fixture(
            module, 'pres-refresh-sources', image_type='landmarks', content=b'stale-map')
        new_path, _marks = self._persisted_map_fixture(
            module, 'pres-refresh-sources', image_type='landmarks', content=b'current-map')
        stale_digest = hashlib.sha256(b'stale-map').hexdigest()
        stale_src = f'/uploads/creative/{self.tenant_a}/revisions/{stale_digest}.png'
        html = (f'<div class="slide"><img src="{stale_src}">'
                '<img src="/uploads/creative/other/revisions/notamap.png"></div>')
        with self.app.app_context():
            refreshed = module._refresh_slide_map_sources(
                html, {}, self.tenant_a, presentation_id='pres-refresh-sources')
        expected = '/uploads/maps/' + os.path.basename(new_path)
        self.assertIn(expected, refreshed)
        self.assertNotIn(stale_src, refreshed)
        self.assertIn('notamap.png', refreshed)
        self.assertIn('data-canonical-map="landmarks"', refreshed)

    def test_refresh_slide_map_sources_keeps_current_frozen_copy(self):
        module = self.application_module
        path, _marks = self._persisted_map_fixture(
            module, 'pres-refresh-current', image_type='overview', content=b'current-overview')
        digest = hashlib.sha256(b'current-overview').hexdigest()
        frozen_src = f'/uploads/creative/{self.tenant_a}/revisions/{digest}.png'
        html = f'<div class="slide"><img src="{frozen_src}"></div>'
        with self.app.app_context():
            refreshed = module._refresh_slide_map_sources(
                html, {}, self.tenant_a, presentation_id='pres-refresh-current')
        self.assertEqual(refreshed, html)

    def test_update_slide_image_replaces_single_image_in_place(self):
        module = self.application_module
        html = ('<div class="slide"><h2>المنظور الكلي</h2>'
                '<img src="/uploads/creative/t/revisions/olddigest.png" alt=""></div>')
        updated, changed = module._replace_slide_image_with_asset(
            html, '/uploads/creative/t/aerial-new.png', asset_token='##MOODBOARD_IMAGE_2##')
        self.assertTrue(changed)
        self.assertIn('/uploads/creative/t/aerial-new.png', updated)
        self.assertNotIn('olddigest.png', updated)
        self.assertIn('data-asset-token="##MOODBOARD_IMAGE_2##"', updated)
        self.assertEqual(updated.count('<img'), 1)
        self.assertIn('<h2>المنظور الكلي</h2>', updated)

    def test_update_slide_image_index_and_chrome_skip(self):
        module = self.application_module
        html = ('<div class="slide">'
                '<img src="/assets/logo.png" class="presentation-chrome-logo">'
                '<img src="/uploads/creative/t/first.png">'
                '<img src="/uploads/creative/t/second.png"></div>')
        updated, changed = module._replace_slide_image_with_asset(
            html, '/uploads/creative/t/new.png', asset_token='##MOODBOARD_IMAGE_1##',
            image_index=2)
        self.assertTrue(changed)
        self.assertIn('/assets/logo.png', updated)
        self.assertIn('/uploads/creative/t/first.png', updated)
        self.assertNotIn('/uploads/creative/t/second.png', updated)
        self.assertIn('/uploads/creative/t/new.png', updated)
        # Without an index the stamped tag is the next update's target.
        updated_again, changed_again = module._replace_slide_image_with_asset(
            updated, '/uploads/creative/t/newer.png', asset_token='##MOODBOARD_IMAGE_1##')
        self.assertTrue(changed_again)
        self.assertIn('/uploads/creative/t/newer.png', updated_again)
        self.assertIn('/uploads/creative/t/first.png', updated_again)

    def test_update_slide_image_appends_box_when_slide_has_none(self):
        module = self.application_module
        html = '<div class="slide"><h2>نص فقط</h2></div>'
        updated, changed = module._replace_slide_image_with_asset(
            html, '/uploads/creative/t/plan.png', asset_token='##PLAN_IMAGE_1##')
        self.assertTrue(changed)
        self.assertIn('data-slide-imagebox', updated)
        self.assertIn('data-asset-token="##PLAN_IMAGE_1##"', updated)
        self.assertIn('/uploads/creative/t/plan.png', updated)

    def test_designer_image_assets_enumerate_every_family(self):
        module = self.application_module
        creative = {
            'cover': '/uploads/creative/t/cover.png',
            'moodboard': ['/uploads/creative/t/mb1.png', '/uploads/creative/t/mb2.png'],
            'moodboard_meta': [{'label': 'الواجهة', 'caption': 'نهاري'},
                               {'label': 'المنظور الكلي ثلاثي الأبعاد'}],
            'interior_components': [{'name': 'اللوبي', 'images': [{'url': '/uploads/creative/t/lobby.png', 'label': 'مدخل'}]}],
            'plans': ['/uploads/creative/t/plan1.png'],
            'plan_meta': [{'title': 'مخطط الدور الأرضي'}],
            'land_photos': [{'url': '/api/project-files/land1', 'name': 'صورة الأرض من الشارع'}],
        }
        assets = module._designer_image_assets(creative)
        tokens = [a['token'] for a in assets]
        self.assertEqual(tokens, ['##IMAGE_COVER##', '##MOODBOARD_IMAGE_1##',
                                  '##MOODBOARD_IMAGE_2##', '##INTERIOR_COMP_1_IMG_1##',
                                  '##PLAN_IMAGE_1##', '##LAND_PHOTO_1##'])
        url, asset = module._designer_image_asset_url('moodboard_image_2', assets)
        self.assertEqual(url, '/uploads/creative/t/mb2.png')
        self.assertIn('المنظور الكلي', asset['label'])
        url, _asset = module._designer_image_asset_url('##AERIAL_IMAGE_3##', assets)
        self.assertEqual(url, '')

    def test_invented_image_token_rescued_to_family_asset(self):
        module = self.application_module
        creative = {'moodboard': ['/u/mb1.png', '/u/mb2.png', '/u/mb3.png']}
        html = '<div class="slide"><img src="##AERIAL_IMAGE_3##"></div>'
        resolved = module.slide_engine._replace_creative_image_placeholders(
            html, creative, 'content')
        self.assertIn('src="/u/mb3.png"', resolved)
        self.assertNotIn('##AERIAL_IMAGE_3##', resolved)
        # Interior wording routes to interior assets.
        creative['interior'] = ['/u/lobby.png']
        resolved = module.slide_engine._replace_creative_image_placeholders(
            '<div class="slide"><img src="##LOBBY_INTERIOR_1##"></div>', creative, 'content')
        self.assertIn('src="/u/lobby.png"', resolved)

    def test_invented_image_token_never_rewrites_text_context(self):
        module = self.application_module
        creative = {'moodboard': ['/u/mb1.png']}
        html = '<div class="slide"><h2>##VIEW_NAME##</h2><img src="##AERIAL_IMAGE_9##"></div>'
        resolved = module.slide_engine._replace_creative_image_placeholders(
            html, creative, 'content')
        self.assertIn('<h2>##VIEW_NAME##</h2>', resolved)
        # An out-of-range invented index stays a token for the dropper.
        self.assertIn('##AERIAL_IMAGE_9##', resolved)

    def test_refresh_slide_asset_sources_repoints_stale_tag(self):
        module = self.application_module
        assets = [{'token': '##MOODBOARD_IMAGE_2##', 'url': '/uploads/creative/t/mb2-new.png',
                   'label': 'x', 'family': 'moodboard'}]
        html = ('<div class="slide"><img src="/uploads/creative/t/revisions/frozen.png" '
                'data-asset-token="##MOODBOARD_IMAGE_2##">'
                '<img src="/uploads/creative/t/other.png"></div>')
        refreshed = module._refresh_slide_asset_sources(html, assets)
        self.assertIn('mb2-new.png', refreshed)
        self.assertNotIn('frozen.png', refreshed)
        self.assertIn('/uploads/creative/t/other.png', refreshed)

    def test_untouched_financial_study_is_not_sent_as_approved_tables(self):
        """The section snapshots itself for every project, so defaults must not become facts."""
        import slide_engine as engine
        defaults_only = {
            'inputs': {'developmentYears': 4, 'developerRate': 10, 'annualFinanceRate': 6,
                       'projectCost': 0, 'landValue': 0, 'totalBuiltUpArea': 0},
            'projection': {'roi': 0, 'irr': 0},
            'dynamicRows': {'components': [], 'revenue': []},
            'tables': {'componentsTable': []},
        }
        self.assertFalse(engine.financial_study_has_real_input(defaults_only))
        # Silence is not neutral: the absence is stated so the model cannot fill the gap.
        absent_note = engine._financial_data_note({'financial_study_model': defaults_only})
        self.assertEqual(absent_note, engine.FINANCIAL_ABSENT_NOTE)
        self.assertNotIn('الجداول المالية المعتمدة أدناه', absent_note)

        entered = dict(defaults_only, inputs=dict(defaults_only['inputs'], projectCost=480000000))
        self.assertTrue(engine.financial_study_has_real_input(entered))
        entered_note = engine._financial_data_note({'financial_study_model': entered})
        self.assertIn('المؤشرات المالية بمسمياتها الأصلية', entered_note)
        # An entered study is copied, never recomputed or extended.
        self.assertIn('فواصل الآلاف', entered_note)
        self.assertIn('الرقم أو المؤشر غير الموجود لا يُكتب', entered_note)
        self.assertIn('لا تحذف صفاً أو عموداً أو سنة', entered_note)

        # A plan for a project with no figures carries no financial slide from any source.
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover', 'design_style': 'image'},
            {'title': 'التحليل المالي والجدوى', 'type': 'content', 'design_style': 'dashboard'},
            {'title': 'مؤشرات الأداء والقيمة المضافة', 'type': 'content', 'design_style': 'dashboard'},
            {'title': 'الموقع والمميزات', 'type': 'content', 'design_style': 'map'},
        ]}
        stripped = engine.strip_financial_slides(json.loads(json.dumps(plan)),
                                                 {'financial_study_model': defaults_only})
        self.assertEqual([slide['title'] for slide in stripped['slides']],
                         ['الغلاف', 'الموقع والمميزات'])
        self.assertEqual(stripped['proposed_count'], 2)
        kept = engine.strip_financial_slides(json.loads(json.dumps(plan)),
                                            {'financial_study_model': entered})
        self.assertEqual(len(kept['slides']), 4)

        by_components = dict(defaults_only,
                             dynamicRows={'components': [{'name': 'شقق سكنية', 'builtArea': 24000}]})
        self.assertTrue(engine.financial_study_has_real_input(by_components))

        index_source = read_frontend_text()
        self.assertIn("if (key === 'financial_study_model') {", index_source)
        self.assertIn('const report = tenantFinancialPresentationReport', index_source)
        self.assertIn("tenantFinancialPresentationReport = financialStudyHasRealInput", index_source)
        # Generating from a name alone can only produce invented content, so it is stated, not hidden.
        self.assertIn('const GENERATION_MIN_FACTS = 6;', index_source)
        self.assertIn('const factCount = countProjectFacts(tenantProjectData);', index_source)

    def test_slide_plan_runs_as_a_polled_job_so_the_proxy_cannot_drop_it(self):
        """A full project needs minutes to plan, and the live proxy kills a request held that long."""
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat_parallel', side_effect=RuntimeError('AI unavailable')):
            queued = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
                'projectData': {'project_name': 'مشروع تجريبي', 'project_type': 'سكني'},
                'background': True,
            })
            self.assertEqual(queued.status_code, 202, queued.get_json())
            self.assertTrue(queued.get_json()['fallbackPlan']['slides'])
            self.assertEqual(queued.get_json()['fallbackPlan']['source'], 'fallback')
            job_id = queued.get_json()['jobId']

            job = {}
            for _ in range(80):
                time.sleep(0.05)
                polled = client.get('/api/slide-plan/jobs/' + job_id, headers=self._headers(self.token_a))
                self.assertEqual(polled.status_code, 200, polled.get_json())
                job = polled.get_json()
                if job.get('status') in ('completed', 'failed'):
                    break

        self.assertEqual(job.get('status'), 'completed', job)
        self.assertTrue(job['plan']['slides'])

        missing = client.get('/api/slide-plan/jobs/00000000-0000-0000-0000-000000000000',
                             headers=self._headers(self.token_a))
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()['failureReason'], 'job_not_found')
        index_source = read_frontend_text()
        self.assertIn('started < 2 * 60 * 1000', index_source)
        self.assertIn('if (completed?.plan || !res.fallbackPlan) return completed;', index_source)
        self.assertIn("plan: { ...res.fallbackPlan, source: 'fallback'", index_source)

    def test_generation_job_idempotency_key_names_the_run_not_just_the_draft(self):
        """ISS-041: re-generating the same draft must register a new job —
        the key carries the approval id, not only the draft id."""
        index_source = read_frontend_text()
        self.assertIn(
            "idempotencyKey: 'gen-' + (window.currentGenerationApprovalId || 'run')",
            index_source)

    def test_site_analysis_endpoint_returns_ai_text_without_large_creative_payload(self):
        client = self.app.test_client()
        enriched = {
            'location_detail': 'Riyadh, Saudi Arabia',
            'main_roads': 'شارع تجريبي رئيسي',
            'secondary_roads': 'شارع فرعي قريب - 1 كم',
            'nearby_landmarks': 'معلم قريب — تعليمي — 5 كم — 8 دقائق',
            'city_landmarks': 'معالم مدينة جدة',
            'population_density': '4500 نسمة/كم²',
        }
        with patch.object(self.application_module, '_collect_site_fields', return_value=(enriched, [], [], [], [], [], None)), \
                patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': 'تحليل عربي مختصر للموقع'}}]
        }) as call_ai:
            response = client.post('/api/site-analysis', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'project_idea': 'فندق بوتيك لرجال الأعمال والسياح',
                    'project_goal': 'إنشاء وجهة ضيافة عملية للمسافرين من رجال الأعمال',
                    'project_stage': 'دراسة جدوى',
                    'initial_features': 'ردهة أعمال ومرافق اجتماعات',
                    'initial_strengths': 'قرب الموقع من المطار ومحور تجاري رئيسي',
                    'nearby_landmarks': 'معلم قريب — تعليمي — 5 كم — 8 دقائق',
                    'tenantCreativeImages': {'cover': 'data:image/png;base64,' + ('A' * 20000)},
                }
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['analysis'], 'تحليل عربي مختصر للموقع')
        self.assertEqual(response.get_json()['fields']['population_density'], '4500 نسمة/كم²')
        self.assertEqual(response.get_json()['fields']['main_roads'], 'شارع تجريبي رئيسي')
        prompt = call_ai.call_args.args[1]
        self.assertNotIn('tenantCreativeImages', prompt)
        self.assertIn('معلم قريب', prompt)
        self.assertIn('فندق بوتيك', prompt)
        self.assertIn('4500 نسمة/كم²', prompt)
        self.assertIn('شارع تجريبي رئيسي', prompt)
        self.assertIn('إنشاء وجهة ضيافة عملية', prompt)
        self.assertIn('دراسة جدوى', prompt)
        self.assertIn('ردهة أعمال ومرافق اجتماعات', prompt)
        self.assertIn('قرب الموقع من المطار', prompt)
        self.assertIn('الكثافة السكانية', prompt)
        # infrastructure was retired from the location section — the prompt must not
        # ask the model to discuss a field that no longer exists.
        self.assertNotIn('البنية التحتية', prompt)
        self.assertIn('فرص الاستثمار', prompt)
        self.assertIn('المعالم القريبة ومعالم المدينة', prompt)
        self.assertEqual(call_ai.call_args.kwargs['reasoning_effort'], 'max')
        self.assertEqual(call_ai.call_args.kwargs['max_tokens'], self.application_module.SITE_ANALYSIS_MAX_TOKENS)

    def test_site_analysis_falls_back_to_openrouter_when_primary_ai_response_fails(self):
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat', side_effect=RuntimeError('primary AI unavailable')), \
                patch.object(self.application_module, 'OPENROUTER_KEY', 'test-openrouter-key'), \
                patch.object(self.application_module, 'call_openrouter_chat', return_value={
                    'choices': [{'message': {'content': 'تحليل من النموذج الاحتياطي'}}]
                }) as fallback:
            response = client.post('/api/site-analysis', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['analysis'], 'تحليل من النموذج الاحتياطي')
        self.assertEqual(fallback.call_args.kwargs['model'], 'google/gemini-3.8-flash')

    def test_project_draft_preserves_selected_landmark_details(self):
        client = self.app.test_client()
        details = [{
            'name': 'معلم مختار', 'category': 'تعليمي', 'lat': 24.01, 'lng': 46.01,
            'distance_km': 4.2, 'duration_minutes': 7,
        }]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'nearby_landmarks': 'معلم مختار — تعليمي — 4.2 كم — 7 دقائق',
                'nearby_landmarks_data': details,
            }
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        self.assertEqual(loaded.status_code, 200, loaded.get_json())
        self.assertEqual(loaded.get_json()['draft']['draft_data']['nearby_landmarks_data'], details)

    def test_custom_sections_can_be_renamed_and_fields_require_a_tenant_section(self):
        client = self.app.test_client()
        headers_a = self._headers(self.token_a)

        created = client.post('/api/field-sections/custom', headers=headers_a, json={
            'key': 'brand_references', 'label': 'Brand references'
        })
        self.assertEqual(created.status_code, 201)

        renamed = client.put('/api/field-sections/custom/brand_references', headers=headers_a, json={
            'label': 'Brand standards'
        })
        self.assertEqual(renamed.status_code, 200)
        available = client.get('/api/field-sections', headers=headers_a).get_json()['available']
        custom_section = next(section for section in available if section['key'] == 'brand_references')
        self.assertEqual(custom_section['label'], 'Brand standards')

        invalid_create = client.post('/api/fields', headers=headers_a, json={
            'fieldKey': 'invalid_section_field', 'fieldLabel': 'Invalid section field',
            'sectionKey': 'not_a_company_section'
        })
        self.assertEqual(invalid_create.status_code, 400)

        valid_create = client.post('/api/fields', headers=headers_a, json={
            'fieldKey': 'brand_standard_note', 'fieldLabel': 'Brand standard note',
            'sectionKey': 'brand_references'
        })
        self.assertEqual(valid_create.status_code, 201)
        field_id = valid_create.get_json()['fieldId']

        # A section from Company A cannot be used by Company B or assigned to
        # an existing field as an arbitrary key.
        cross_tenant = client.post('/api/fields', headers=self._headers(self.token_b), json={
            'fieldKey': 'cross_tenant_section_field', 'fieldLabel': 'Cross-tenant section field',
            'sectionKey': 'brand_references'
        })
        self.assertEqual(cross_tenant.status_code, 400)
        invalid_update = client.put('/api/fields/' + field_id, headers=headers_a, json={
            'sectionKey': 'not_a_company_section'
        })
        self.assertEqual(invalid_update.status_code, 400)

        missing_rename = client.put('/api/field-sections/custom/not_real', headers=headers_a, json={
            'label': 'No section'
        })
        self.assertEqual(missing_rename.status_code, 404)

    def test_company_admin_draft_preserves_sections_and_approval_state(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        saved = client.post('/api/project-draft', headers=headers, json={
            'draftData': {'project_name': 'Test project'}, 'sectionStatuses': {}, 'status': 'draft'
        })
        self.assertEqual(saved.status_code, 200)

        section = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionKey': 'basic', 'sectionStatus': 'approved'
        })
        self.assertEqual(section.status_code, 200)

        # Legacy autosaves send {}; this must not erase the per-section decision.
        resaved = client.post('/api/project-draft', headers=headers, json={
            'draftData': {'project_name': 'Test project updated'}, 'sectionStatuses': {}, 'status': 'draft'
        })
        self.assertEqual(resaved.status_code, 200)
        draft = client.get('/api/project-draft', headers=headers).get_json()['draft']
        self.assertEqual(draft['section_statuses'], {'basic': 'approved'})

        request_approval = client.post('/api/project-draft/request-approval', headers=headers, json={})
        self.assertEqual(request_approval.status_code, 200)
        draft_id = request_approval.get_json()['draft']['id']

        review = client.post('/api/project-draft/review', headers=headers, json={
            'draftId': draft_id, 'status': 'approved', 'note': 'Reviewed in test'
        })
        self.assertEqual(review.status_code, 200)
        approved = client.get('/api/project-draft/approval-status', headers=headers).get_json()['approval']
        self.assertEqual(approved['status'], 'sections_approved')
        self.assertEqual(approved['review_note'], 'Reviewed in test')

        # Editing a previously approved section returns the unified draft to work-in-progress.
        returned = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionKey': 'basic', 'sectionStatus': 'draft'
        })
        self.assertEqual(returned.status_code, 200)
        current = client.get('/api/project-draft', headers=headers).get_json()['draft']
        self.assertEqual(current['status'], 'sections_in_progress')

    def test_admin_approves_draft_directly_while_employee_request_stays_pending(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        with self.app.app_context():
            employee_id = db.create_user(
                self.tenant_a, 'Employee', 'employee@example.test', 'hash', role='employee')
        employee_token = auth.create_token(
            self.tenant_a, 'employee@example.test', user_id=employee_id,
            user_name='Employee', user_role='employee')
        employee_headers = self._headers(employee_token)

        # An admin approves a draft whose sections were never approved.
        saved = client.post('/api/project-draft', headers=headers, json={
            'draftId': 'draft-direct-approve',
            'draftData': {'draftId': 'draft-direct-approve', 'project_name': 'Direct'},
            'sectionStatuses': {}, 'status': 'draft'})
        self.assertEqual(saved.status_code, 200)
        review = client.post('/api/project-draft/review', headers=headers, json={
            'draftId': 'draft-direct-approve', 'status': 'approved'})
        self.assertEqual(review.status_code, 200, review.get_json())
        approved = client.get(
            '/api/project-draft/draft-direct-approve', headers=headers).get_json()['draft']
        self.assertEqual(approved['status'], 'sections_approved')

        # An employee without the approvals permission cannot use the review route.
        denied = client.post('/api/project-draft/review', headers=employee_headers, json={
            'draftId': 'draft-direct-approve', 'status': 'approved'})
        self.assertEqual(denied.status_code, 403)

        # The employee path still goes through pending: one approved section is
        # enough to submit (approving location would need the full map
        # workflow), and the request waits for an admin decision.
        owned = client.post('/api/project-draft', headers=employee_headers, json={
            'draftId': 'draft-employee-waiting',
            'draftData': {'draftId': 'draft-employee-waiting', 'project_name': 'Waiting'},
            'sectionStatuses': {}, 'status': 'draft'})
        self.assertEqual(owned.status_code, 200)
        sections_resp = client.post('/api/project-draft/section-status', headers=employee_headers, json={
            'sectionKey': 'basic', 'sectionStatus': 'approved'})
        self.assertEqual(sections_resp.status_code, 200)
        requested = client.post('/api/project-draft/request-approval', headers=employee_headers, json={
            'draftId': 'draft-employee-waiting'})
        self.assertEqual(requested.status_code, 200, requested.get_json())
        waiting = client.get(
            '/api/project-draft/draft-employee-waiting', headers=employee_headers).get_json()['draft']
        self.assertEqual(waiting['status'], 'section_approval_pending')

        # And the admin decision on that pending request still lands.
        decision = client.post('/api/project-draft/review', headers=headers, json={
            'draftId': 'draft-employee-waiting', 'status': 'approved'})
        self.assertEqual(decision.status_code, 200)
        final = client.get(
            '/api/project-draft/draft-employee-waiting', headers=headers).get_json()['draft']
        self.assertEqual(final['status'], 'sections_approved')

        index_source = read_frontend_text()
        self.assertIn('async function approveProjectDraftById(draftId)', index_source)
        self.assertIn("'/api/project-draft/review'", index_source)

    def test_training_entries_are_tenant_isolated_and_not_public_uploads(self):
        client = self.app.test_client()
        created = client.post('/api/training', headers=self._headers(self.token_a), json={
            'title': 'Tenant A reference', 'content': 'Private design instruction', 'category': 'reference'
        })
        self.assertEqual(created.status_code, 201)
        entry_id = created.get_json()['entryId']

        other_update = client.put('/api/training/' + entry_id, headers=self._headers(self.token_b), json={'is_active': False})
        other_delete = client.delete('/api/training/' + entry_id, headers=self._headers(self.token_b))
        self.assertEqual(other_update.status_code, 404)
        self.assertEqual(other_delete.status_code, 404)

        own_entry = client.get('/api/training', headers=self._headers(self.token_a)).get_json()['entries'][0]
        self.assertEqual(own_entry['is_active'], 1)
        self.assertNotIn('image_path', own_entry)
        self.assertEqual(client.get('/uploads/training/unknown.png').status_code, 404)

    def test_uploaded_training_image_requires_consent_and_tenant_authentication(self):
        client = self.app.test_client()
        # Valid 1x1 PNG, kept inline so the test does not need network or fixtures.
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        original_key = self.application_module.OPENROUTER_KEY
        self.application_module.OPENROUTER_KEY = None
        try:
            denied = client.post('/api/training/upload-image', headers=self._headers(self.token_a), data={
                'image': (io.BytesIO(png_bytes), 'reference.png'), 'imageType': 'reference'
            }, content_type='multipart/form-data')
            self.assertEqual(denied.status_code, 400)

            uploaded = client.post('/api/training/upload-image', headers=self._headers(self.token_a), data={
                'image': (io.BytesIO(png_bytes), 'reference.png'),
                'imageType': 'reference',
                'description': 'Private tenant reference',
                'companyDataConsent': 'true',
            }, content_type='multipart/form-data')
        finally:
            self.application_module.OPENROUTER_KEY = original_key

        self.assertEqual(uploaded.status_code, 200)
        image_url = uploaded.get_json()['imagePath']
        own_image = client.get(image_url, headers=self._headers(self.token_a))
        self.assertEqual(own_image.status_code, 200)
        own_image.close()
        self.assertEqual(client.get(image_url, headers=self._headers(self.token_b)).status_code, 404)

    def test_icons_and_non_google_router_are_absent_from_output_paths(self):
        from slide_engine import postprocess_slide

        html = '<div class="slide"><svg><path /></svg><span class="icon">x</span>🏗️ محتوى</div>'
        rendered = postprocess_slide(html, 'content')
        self.assertNotIn('<svg', rendered.lower())
        self.assertNotIn('class="icon"', rendered.lower())
        self.assertNotIn('🏗', rendered)

        maps_source = read_module_source('maps_service.py')
        self.assertNotIn('router.project-osrm.org', maps_source)
        self.assertIn('maps.googleapis.com/maps/api/directions/json', maps_source)

    def test_visual_concept_replaces_legacy_image_workflow_pages(self):
        index_source = read_frontend_text()
        self.assertIn('id="section-visual-concept"', index_source)
        self.assertIn("createProjectSectionHeader('section-visual-concept', 'التصور البصري')", index_source)
        self.assertIn('function addVisualConceptSection(form', index_source)
        self.assertIn("tenantVisualConceptPage: '/app/projects/visual-concept'", index_source)
        self.assertNotIn('اختاري كرت التصور الخارجي أو الداخلي', index_source)
        self.assertIn('data-visual-concept-target="external"', index_source)
        self.assertIn('data-visual-concept-target="internal"', index_source)
        self.assertIn('data-visual-caption', index_source)
        self.assertNotIn('data-conceptual-plan-caption', index_source)
        self.assertNotIn('function addConceptualPlansSection(form, before)', index_source)
        self.assertNotIn('function conceptualPlansNeedCaptions()', index_source)
        self.assertIn('<label>وصف الصورة</label>', index_source)
        self.assertNotIn('placeholder="وصف الصورة (اختياري)"', index_source)
        self.assertIn('visualConceptInteriorComponentSelect', index_source)
        self.assertIn('function uploadVisualConceptInteriorReferences', index_source)
        self.assertIn('function uploadVisualConceptSlotImage(slotId, input)', index_source)
        self.assertIn('VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 30', index_source)
        self.assertIn('deletedInteriorSlots', index_source)
        self.assertIn('function deleteVisualConceptInteriorField', index_source)
        self.assertIn('data-visual-action="delete-interior-field"', index_source)
        self.assertIn("data-visual-action=\"add-interior\"", index_source)
        self.assertIn('function showVisualConceptView(view)', index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        self.assertIn("data-key=\"visual_concept\"", index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        self.assertIn('saveProjectAsDraft', index_source)
        self.assertIn("api('POST', '/api/visual-concept/prompt'", index_source)
        self.assertIn("apiWithTimeout('POST', '/api/visual-concept/generate'", index_source)
        self.assertIn('visual-concept-stack', index_source)
        self.assertIn('.visual-concept-preview img {', index_source)
        self.assertIn('object-fit: contain', index_source)
        self.assertRegex(index_source, r'\.visual-concept-stack \{\s*display: grid;\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);')
        self.assertIn('visualConceptStyleReferenceInput', index_source)
        self.assertIn("input.dataset.projectFileType = 'visual_reference'", index_source)
        self.assertIn('multiple accept="image/png,image/jpeg,image/jpg,image/webp"', index_source)
        self.assertIn('styleReferenceFileIds', index_source)
        self.assertIn('visualConceptImageUrl(response.image)', index_source)
        self.assertIn('data-visual-upload', index_source)
        self.assertIn('data-visual-title', index_source)
        self.assertIn('function visualConceptCanRenameSlot(slotId)', index_source)
        self.assertNotIn('visual-concept-grid', index_source)
        # The legacy floor-design page is gone: plans are cards here, and the isometric
        # placeholder section was removed entirely.
        self.assertNotIn('tenantFloorDesignPage', index_source)
        self.assertNotIn('floor_visual_design', index_source)
        self.assertNotIn('/api/floor-design/', index_source)
        self.assertNotIn('/api/floor-design/', read_module_source('app.py'))
        self.assertIn('data-visual-concept-target="plans2d"', index_source)
        self.assertNotIn('data-visual-concept-target="isometric"', index_source)
        self.assertIn('id="visualConceptPlansView"', index_source)
        self.assertNotIn('visualConceptIsometricView', index_source)
        self.assertNotIn('visualConceptHomeIsometricStatus', index_source)
        # Plans run the same slot flow as every other visual card: each plan record is
        # mirrored by slots[plan.id], so prompt → edit → generate → approve all reuse the
        # existing pipeline, while plans2d stays the durable record slides read.
        self.assertIn('VISUAL_CONCEPT_MAX_PLANS = 30', index_source)
        self.assertIn('function normalizeVisualConceptPlans(raw)', index_source)
        self.assertIn('function renderVisualConceptPlans()', index_source)
        self.assertIn('function addVisualConceptPlan()', index_source)
        self.assertIn('function isVisualConceptPlanSlot(slotId)', index_source)
        self.assertIn('function visualConceptPlanSeed(plan)', index_source)
        self.assertIn('async function uploadVisualConceptPlanImages(input)', index_source)
        self.assertIn('function deleteVisualConceptPlan(planId)', index_source)
        self.assertIn('id="visualConceptPlansWorkflow"', index_source)
        self.assertIn('data-visual-plans-tab="generate"', index_source)
        self.assertIn('data-visual-plans-tab="upload"', index_source)
        self.assertIn("api('POST', '/api/visual-concept/plans-verify'", index_source)
        self.assertIn("api('POST', '/api/visual-concept/plans-boundary'", index_source)
        self.assertIn("api('POST', '/api/visual-concept/plans-distribution'", index_source)
        self.assertIn("api('POST', '/api/visual-concept/plans-distribution-check'", index_source)
        self.assertIn("api('POST', '/api/visual-concept/plans-prompts'", index_source)
        self.assertIn("const conflicts = checks.filter(item => item.result === 'متعارض')", index_source)
        self.assertIn('const canApprove = !conflicts.length', index_source)
        self.assertIn("if (conflicts.length || (!checks.length && !workflow.verification.canProceed)) return;", index_source)
        self.assertIn("WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')", index_source)
        self.assertIn('plans-conflict-solution', index_source)
        self.assertIn("WFT('plans.proposed_solution', 'الحل المقترح:')", index_source)
        self.assertIn("const defaultStage = !verified ? 'verify'", index_source)
        self.assertIn("const activeStage = requestedStage", index_source)
        self.assertIn("data-plans-workflow-tab=\"verify\"", index_source)
        self.assertIn("data-plans-workflow-tab=\"boundary\"", index_source)
        self.assertIn("data-plans-workflow-tab=\"generate\"", index_source)
        self.assertIn('<ol class="plans-workflow-steps">', index_source)
        self.assertNotIn('plans-workflow-stage-tabs', index_source)
        self.assertNotIn('visual-concept-mode-btn" data-plans-workflow-tab', index_source)
        self.assertNotIn("data-plans-workflow-action=\"back-verify\"", index_source)
        self.assertNotIn("data-plans-workflow-action=\"back-boundary\"", index_source)
        self.assertIn("data-plans-workflow-action=\"open-land-data\"", index_source)
        self.assertIn('data-plans-workflow-action="propose-distribution"', index_source)
        self.assertIn('data-plans-workflow-action="check-distribution"', index_source)
        self.assertIn('data-plans-workflow-action="approve-distribution"', index_source)
        self.assertIn('data-plans-workflow-action="add-distribution-row"', index_source)
        self.assertIn('data-dist-field="', index_source)
        self.assertIn('data-dist-remove="', index_source)
        self.assertIn('رسم الحدود وتوزيع المكونات', index_source)
        self.assertNotIn('data-plan-boundary-field', index_source)
        self.assertNotIn('data-plans-boundary-rows', index_source)
        self.assertIn('plans-workflow-success', index_source)
        self.assertIn('data-visual-action="delete-plan"', index_source)
        self.assertNotIn('data-visual-plan-title', index_source)
        self.assertNotIn('data-visual-plan-description', index_source)
        self.assertNotIn('visualConceptPlansGenerateButton', index_source)
        self.assertIn("new Set(['home', 'external', 'internal', 'plans2d'])", index_source)
        self.assertIn('plans2d: plans', index_source)
        self.assertIn('<h3>المخططات</h3>', index_source)
        self.assertNotIn('المخططات 2D', index_source)
        self.assertNotIn('نفس المبنى المعتمد', index_source)
        self.assertNotIn('tenantMainImagePage', index_source)
        self.assertNotIn('tenantMoodboardPage', index_source)
        self.assertNotIn('tenantMainImagePromptInput', index_source)
        self.assertNotIn('tenantMoodboardPreview', index_source)

    def test_ui_carries_no_static_how_to_hints(self):
        index_source = read_frontend_text()
        # Owner rule: the screen states what a thing is, never how to operate it.
        for instruction in (
            'ولّد الصورة الرئيسية أولًا من بيانات المشروع',
            'اختياري: ارفع حتى 5 صور لمبانٍ أو واجهات تعجبك',
            'اختر القسم من القائمة الجانبية',
            'عمود «إلى» يُحسب تلقائيًا من البداية والمدة',
            'النطاق يحدد دائرة البحث عن المنافسين',
            'المدينة والحي مرتبطان بقسم الموقع والخرائط',
            'توليد المنافسين يمسح الجدول ويضع النتيجة الجديدة',
            'اضغط على المخطط للتكبير الكامل',
            'حدد الأقسام التي يمكن للموظف الوصول إليها',
            'فعّل رسم حدود الموقع ثم أضف النقاط',
        ):
            self.assertNotIn(instruction, index_source, instruction)
        # Status and empty-state text stays: it reports state, it does not teach.
        for kept in (
            'لا توجد بنود مدخلة في هذا الجدول.',
            'زوايا التصور الخارجي مقفلة حتى اعتماد الصورة الرئيسية.',
            'تحليل الموقع يحتاج اعتمادًا قبل توليد الخرائط',
            'لم تُرفع صور للأرض.',
        ):
            self.assertIn(kept, index_source, kept)

    def test_visual_concept_approval_is_one_toggle_per_image(self):
        index_source = read_frontend_text()
        start = index_source.index('function renderVisualConceptSlot(slotDef, locked)')
        body = index_source[start:index_source.index('function visualConceptImageUrl(url)')]
        # Same rule as a section: one button, status مسودة / معتمد, card frozen while approved.
        self.assertIn("(approved ? 'unapprove' : 'approve')", body)
        self.assertIn("(approved ? 'الغاء الاعتماد' : 'اعتماد')", body)
        self.assertIn("approved ? 'معتمد'", body)
        self.assertIn("(approved ? ' section-locked' : '')", body)
        self.assertIn('const frozen = approved;', body)
        self.assertNotIn('اعتماد الصورة<', body)
        self.assertIn('function unapproveVisualConceptImage(slotId)', index_source)
        self.assertIn("else if (action === 'unapprove') unapproveVisualConceptImage(slotId);", index_source)
        self.assertIn(".visual-concept-card.section-locked button:not([data-visual-action=\"unapprove\"])", index_source)
        # The legacy tenantCreativeImages mirrors hold previews, so they must not decide approval.
        self.assertIn('if (!stated.cover && tenantCreativeImages.cover) {', index_source)
        self.assertIn('if (!stated[item.id] && moodboardImages[index]) {', index_source)
        self.assertIn("if (slotId === 'cover' && tenantCreativeImages) tenantCreativeImages.cover = '';", index_source)

    def test_visual_concept_generation_writes_to_the_live_slot(self):
        index_source = read_frontend_text()
        start = index_source.index('async function generateVisualConceptImage(slotId)')
        body = index_source[start:index_source.index('function approveVisualConceptImage(slotId)')]
        # renderVisualConceptPage reassigns tenantVisualConceptState, so a slot captured
        # before a render is detached and the generated image is written to a dead object.
        self.assertIn('const liveSlot = () => tenantVisualConceptState.slots[slotId];', body)
        self.assertIn('liveSlot().imageUrl = visualConceptImageUrl(response.image);', body)
        self.assertNotIn('const slot = tenantVisualConceptState.slots[slotId];', body)
        self.assertNotIn('slot.imageUrl =', body)
        chat_start = index_source.index('async function sendVisualConceptChat(slotId)')
        chat_body = index_source[chat_start:chat_start + 2200]
        self.assertIn('liveSlot().prompt = response.prompt;', chat_body)
        self.assertNotIn('slot.chat.push({ role: \'assistant\'', chat_body)

    def test_plans_workflow_writes_responses_to_the_live_workflow(self):
        index_source = read_frontend_text()
        # renderVisualConceptPage reassigns tenantVisualConceptState, so a workflow
        # captured before the API await is detached and the response lands on a dead
        # object — the generate stage then stayed a bare "prompts not ready" message.
        start = index_source.index('async function prepareVisualConceptPlansPrompts()')
        body = index_source[start:index_source.index('function addVisualConceptPlan()', start)]
        self.assertLess(
            body.index("api('POST', '/api/visual-concept/plans-prompts'"),
            body.index('const workflow = visualConceptPlansWorkflowState()'))
        self.assertIn('workflow.promptsError', body)
        self.assertIn('visualConceptPlansPromptsPending', index_source)
        boundary_start = index_source.index('async function refreshVisualConceptPlansBoundary()')
        boundary_body = index_source[boundary_start:index_source.index('async function reviseVisualConceptPlansBoundaryWithAi()', boundary_start)]
        self.assertLess(
            boundary_body.index("api('POST', '/api/visual-concept/plans-boundary'"),
            boundary_body.index('const workflow = visualConceptPlansWorkflowState()'))
        ai_start = index_source.index('async function reviseVisualConceptPlansBoundaryWithAi()')
        ai_body = index_source[ai_start:index_source.index('function approveVisualConceptPlansBoundary()', ai_start)]
        self.assertLess(
            ai_body.index("api('POST', '/api/visual-concept/plans-boundary'"),
            ai_body.index('const workflow = visualConceptPlansWorkflowState()'))
        render_start = index_source.index('function renderVisualConceptPlansWorkflow()')
        render_body = index_source[render_start:index_source.index('function renderVisualConceptPlans()', render_start)]
        # A draft saved between boundary approval and prompt preparation used to reopen
        # on a permanently empty generate stage; the render now re-arms preparation and
        # surfaces the last failure instead of a bare hint.
        self.assertIn('prepareVisualConceptPlansPrompts();', render_body)
        self.assertIn('promptsError', render_body)
        # Exterior prompts ship the workflow too, so the server can ground them on
        # the same deterministic measurements the plan diagrams draw from.
        payload_start = index_source.index('async function collectVisualConceptPayload(slotId)')
        payload_body = index_source[payload_start:index_source.index('function visualConceptSlotLocked', payload_start)]
        self.assertIn(
            'plansWorkflow: normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow),',
            payload_body)
        self.assertNotIn(': null', payload_body)

    def test_visual_concept_requires_real_project_facts_and_cover_before_moodboard(self):
        client = self.app.test_client()
        source = read_module_source('app.py')
        self.assertIn("VISUAL_CONCEPT_MOODBOARD_SLOTS = ('right', 'left', 'top', 'back')", source)
        self.assertIn("VISUAL_CONCEPT_EXTERNAL_SLOTS = ('cover', 'right', 'left', 'top', 'back')", source)
        self.assertIn("'overview_map', 'خريطة الأرض / المبنى'", source)
        self.assertIn('style_reference_file_id', source)
        self.assertIn('style_reference_file_ids', source)
        self.assertIn('VISUAL_CONCEPT_MAX_REFERENCE_IMAGES = 5', source)
        self.assertIn('VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 4', source)
        self.assertIn('You are a smart editor of an existing English architectural image prompt.', source)
        self.assertIn('Current prompt (do not discard):', source)
        self.assertIn('def _visual_concept_slot_label(slot_id, facts=None):', source)
        self.assertEqual(self.application_module._visual_concept_slot_label('right', {'slot_label': 'الواجهة الشمالية'}), 'الواجهة الشمالية')
        self.assertEqual(self.application_module._visual_concept_slot_label('right', {}), 'يمين')
        self.assertIn("conceptual_plan", source)
        self.assertNotIn("facts.get('land_photo_ids')", source)
        self.assertIn('visual_reference', self.application_module.PROJECT_FILE_TYPES)
        self.assertIn('visual_reference', self.application_module.PROJECT_IMAGE_ONLY_TYPES)
        self.assertIn('approved_financial_area', source)

        incomplete = client.post('/api/visual-concept/preflight', headers=self._headers(self.token_a), json={
            'projectData': {'project_name': 'برج الاختبار'}
        })
        self.assertEqual(incomplete.status_code, 400, incomplete.get_json())
        self.assertEqual(incomplete.get_json()['error_code'], 'VISUAL_CONCEPT_DATA_INCOMPLETE')
        missing_keys = {item['key'] for item in incomplete.get_json()['missingFields']}
        self.assertIn('approved_financial_area', missing_keys)
        self.assertIn('overview_map', missing_keys)

        facts = {
            'project_name': 'برج الاختبار',
            'project_idea': 'أبراج مكتبية على أرض تجارية',
            'land_and_building_summary': 'أرض تجارية بواجهة شرقية وغربية',
            'target_audience': 'شركات ومكاتب',
            'approved_financial_area': 8500,
            'approved_floor_count': 12,
            'approved_coverage_ratio': 60,
            'facades_count': 2,
            'facades_directions': 'شرق وغرب',
            'allowed_uses': 'تجاري مكتبي',
            'directions_table': [
                {'direction': 'east', 'regulation_text': 'شارع تجاري 30م'},
                {'direction': 'west', 'regulation_text': 'شارع فرعي 15م'},
            ],
            'project_components_data': [{'name': 'مكاتب', 'useType': 'office', 'units': 20, 'builtArea': 4000}],
            'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'}},
        }
        plan_images = {
            'site': '/uploads/creative/plan_site.png',
            'uses': '/uploads/creative/plan_uses.png',
            'massing': '/uploads/creative/plan_massing.png',
        }
        ready = client.post('/api/visual-concept/preflight', headers=self._headers(self.token_a), json={'projectData': facts})
        self.assertEqual(ready.status_code, 200, ready.get_json())
        self.assertTrue(ready.get_json()['success'])

        # Exterior slots render the approved plan diagrams: without the three
        # plan images the request stops before even reaching the cover check.
        moodboard_blocked = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'right',
            'prompt': 'Right elevation',
            'projectData': facts,
        })
        self.assertEqual(moodboard_blocked.status_code, 400, moodboard_blocked.get_json())
        self.assertEqual(moodboard_blocked.get_json()['error_code'], 'PLANS_IMAGES_REQUIRED')

        cover_blocked = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'cover',
            'prompt': 'Hero image from the project facts',
            'projectData': facts,
        })
        self.assertEqual(cover_blocked.status_code, 400, cover_blocked.get_json())
        self.assertEqual(cover_blocked.get_json()['error_code'], 'PLANS_IMAGES_REQUIRED')

        moodboard_no_cover = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'right',
            'prompt': 'Right elevation',
            'planImages': plan_images,
            'projectData': facts,
        })
        self.assertEqual(moodboard_no_cover.status_code, 400, moodboard_no_cover.get_json())
        self.assertEqual(moodboard_no_cover.get_json()['error_code'], 'COVER_REQUIRED')

        generated = 'data:image/png;base64,AAAA'
        with patch.object(self.application_module, 'call_images_api', return_value=generated) as image_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/cover.png'), \
                patch.object(self.application_module, '_prepare_image_reference_for_model', side_effect=lambda url, tenant_id=None: f'data:image/png;base64,{str(url).rsplit("/", 1)[-1]}'):
            cover = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'cover',
                'prompt': 'Hero image from the project facts',
                'planImages': plan_images,
                'projectData': facts,
            })
        self.assertEqual(cover.status_code, 200, cover.get_json())
        self.assertEqual(cover.get_json()['image'], '/uploads/creative/cover.png')
        self.assertTrue(image_call.called)
        self.assertEqual(image_call.call_args.args[0], 'Hero image from the project facts')
        cover_refs = [str(item) for item in image_call.call_args.args[1]]
        self.assertTrue(any('plan_site.png' in item for item in cover_refs))
        self.assertTrue(any('plan_massing.png' in item for item in cover_refs))

        with patch.object(self.application_module, '_visual_concept_generate_prompt_text', return_value=('Revised right prompt', 'تم')):
            east_prompt = client.post('/api/visual-concept/prompt', headers=self._headers(self.token_a), json={
                'slotId': 'east',
                'coverImage': '/uploads/creative/cover.png',
                'planImages': plan_images,
                'projectData': facts,
            })
        self.assertEqual(east_prompt.status_code, 200, east_prompt.get_json())
        self.assertEqual(east_prompt.get_json()['slotId'], 'right')
        self.assertEqual(east_prompt.get_json()['prompt'], 'Revised right prompt')

        # Exterior prompts ground on the same deterministic measurements the plan
        # diagrams draw from — even before the plans workflow runs — while the
        # diagram's color legend and labelling rules stay out of render prompts.
        captured_facts = {}

        def _capture_prompt_facts(facts_arg, _slot_id, **_kwargs):
            captured_facts.update(facts_arg)
            return ('Grounded right prompt', 'تم')

        with patch.object(self.application_module, '_visual_concept_generate_prompt_text', side_effect=_capture_prompt_facts):
            grounded = client.post('/api/visual-concept/prompt', headers=self._headers(self.token_a), json={
                'slotId': 'right',
                'coverImage': '/uploads/creative/cover.png',
                'planImages': plan_images,
                'projectData': facts,
            })
        self.assertEqual(grounded.status_code, 200, grounded.get_json())
        self.assertEqual(captured_facts.get('plan_image_urls'), list(plan_images.values()))
        plan_context = captured_facts.get('approved_plan_context') or ''
        self.assertIn('APPROVED PLAN CONTEXT', plan_context)
        self.assertIn('Approved floor count/height: 12', plan_context)
        self.assertIn('مكاتب', plan_context)
        self.assertIn('شارع تجاري 30م', plan_context)
        self.assertNotIn('Fixed color code', plan_context)
        self.assertNotIn('NOT TO SCALE', plan_context)

        interior_blocked = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'interior_comp-1',
            'prompt': 'Apartment interior',
            'componentId': 'comp-1',
            'projectData': {
                **facts,
                'project_components_data': [{'id': 'comp-1', 'name': 'شقق', 'useType': 'residential', 'units': 12}],
            },
        })
        self.assertEqual(interior_blocked.status_code, 400, interior_blocked.get_json())
        self.assertEqual(interior_blocked.get_json()['error_code'], 'COVER_REQUIRED')

        with patch.object(self.application_module, 'call_images_api', return_value='data:image/png;base64,BBBB') as interior_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/interior.png'), \
                patch.object(self.application_module, '_prepare_image_reference_for_model', side_effect=lambda url, tenant_id=None: f'data:image/png;base64,{str(url).rsplit("/", 1)[-1]}'), \
                patch.object(self.application_module, '_visual_concept_project_file_data_uri', side_effect=lambda file_id, tenant_id=None: f'data:image/png;base64,{file_id}'):
            interior = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'interior_comp-1',
                'prompt': 'Apartment interior',
                'componentId': 'comp-1',
                'coverImage': '/uploads/creative/cover.png',
                'referenceFileIds': ['ref-a', 'ref-b', 'ref-c', 'ref-d', 'ref-e'],
                'projectData': {
                    **facts,
                    'project_components_data': [{'id': 'comp-1', 'name': 'شقق', 'useType': 'residential', 'units': 12}],
                },
            })
        self.assertEqual(interior.status_code, 200, interior.get_json())
        self.assertEqual(interior.get_json()['slotId'], 'interior_comp-1')
        self.assertTrue(interior_call.called)
        self.assertEqual(interior_call.call_args.args[0], 'Apartment interior')
        self.assertEqual(interior.get_json()['referenceCount'], 6)
        references = interior_call.call_args.args[1]
        self.assertEqual(len(references), 6)
        self.assertIn('cover.png', str(references[0]))
        self.assertTrue(any('ref-a' in str(item) for item in references))

        # Plan slots are the planning diagrams: they do not wait for the hero image —
        # their geometry reference is the approved land map, not the cover render.
        self.assertTrue(self.application_module._visual_concept_is_plan_slot('plan_site'))
        self.assertFalse(self.application_module._visual_concept_is_plan_slot('right'))
        self.assertEqual(
            self.application_module._visual_concept_normalize_slot('plan_1700_abc'), 'plan_1700_abc')
        self.assertEqual(
            self.application_module._visual_concept_slot_label('plan_site', {}), 'الموقع العام المبسط')

        with patch.object(self.application_module, '_visual_concept_generate_prompt_text', side_effect=AssertionError('plan drafts ship verbatim')):
            plan_prompt = client.post('/api/visual-concept/prompt', headers=self._headers(self.token_a), json={
                'slotId': 'plan_site',
                'planDescription': 'مخطط موقع عام مبسط',
                'plansWorkflow': {'verification': {'approved': True}, 'boundary': {'approved': True}, 'distribution': {'approved': True}},
                'projectData': facts,
            })
        self.assertEqual(plan_prompt.status_code, 200, plan_prompt.get_json())
        self.assertEqual(plan_prompt.get_json()['slotId'], 'plan_site')
        self.assertIn('APPROVED DISTRIBUTION MODEL', plan_prompt.get_json()['prompt'])
        self.assertIn('DRAWING REQUESTED', plan_prompt.get_json()['prompt'])

        with patch.object(self.application_module, '_visual_concept_generate_prompt_text', return_value=('Edited plan prompt', 'تم')):
            plan_edit = client.post('/api/visual-concept/prompt', headers=self._headers(self.token_a), json={
                'slotId': 'plan_site',
                'planDescription': 'مخطط موقع عام مبسط',
                'instruction': 'وسّع اللاندسكيب',
                'plansWorkflow': {'verification': {'approved': True}, 'boundary': {'approved': True}, 'distribution': {'approved': True}},
                'projectData': facts,
            })
        self.assertEqual(plan_edit.status_code, 200, plan_edit.get_json())
        self.assertEqual(plan_edit.get_json()['prompt'], 'Edited plan prompt')

        with patch.object(self.application_module, 'call_images_api', return_value='data:image/png;base64,CCCC') as plan_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/plan.png'), \
                patch.object(self.application_module, '_prepare_image_reference_for_model', side_effect=lambda url, tenant_id=None: f'data:image/png;base64,{str(url).rsplit("/", 1)[-1]}'):
            plan = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'plan_site',
                'prompt': 'Conceptual site plan',
                'plansWorkflow': {'verification': {'approved': True}, 'boundary': {'approved': True}, 'distribution': {'approved': True}},
                'projectData': facts,
            })
        self.assertEqual(plan.status_code, 200, plan.get_json())
        self.assertEqual(plan.get_json()['slotId'], 'plan_site')
        self.assertEqual(plan.get_json()['image'], '/uploads/creative/plan.png')
        self.assertTrue(plan_call.called)
        self.assertEqual(plan_call.call_args.kwargs.get('model'), self.application_module.VISUAL_CONCEPT_IMAGE_MODEL)
        plan_refs = plan_call.call_args.args[1]
        self.assertTrue(any('overview.png' in str(item) for item in plan_refs))

        index_source = read_frontend_text()
        self.assertIn('visualConceptInteriorComponentSelect', index_source)
        self.assertIn('function visualConceptInteriorSlotId', index_source)
        self.assertNotIn("function addConceptualPlansSection(form, before)", index_source)
        self.assertNotIn('data-key="conceptual_plans"', index_source)
        self.assertEqual(self.application_module._visual_concept_interior_component_id('interior_comp-1::3'), 'comp-1')

    def test_plans_workflow_verifies_sources_anonymously_and_uses_boundary_context(self):
        module = self.application_module
        client = self.app.test_client()
        points = [
            {'point': 'P1', 'eastings': 511085.849, 'northings': 2392264.840},
            {'point': 'P2', 'eastings': 511189.416, 'northings': 2392298.825},
            {'point': 'P3', 'eastings': 511198.442, 'northings': 2392262.273},
        ]
        project_data = {
            'project_name': 'The View',
            'city': 'جدة',
            'district': 'الشاطئ',
            'croquis_land_area': 7012,
            'approved_floor_count': 52,
            'approved_coverage_ratio': 60,
            'survey_coordinates': points,
            'directions_table': [{'direction': 'west', 'regulation_text': 'كورنيش 16م'}],
            'project_components_data': [
                {'name': 'Luxury Apartments', 'useType': 'residential', 'units': 244, 'floorRange': '26-52'}
            ],
            'land_documents_analysis': {
                'parcels': [{'croquis_land_area': 7012, 'coverage_ratio': 60, 'setbacks': '5m west; 3m east', 'table_floors': 52}],
                'conflicts': [{'description': 'قيمة تحتاج تأكيدًا في اشتراطات1.pdf صفحة 4'}]
            }
        }
        verification_payload = {
            'checks': [{
                'item': 'الارتدادات', 'project': '5m غربًا', 'regulatory': '5m غربًا',
                'result': 'متعارض', 'issues': ['راجع اشتراطات1.pdf صفحة 4'], 'suggestion': 'غيّر القيمة في قسم المساحات من 60000 إلى 42072.72', 'action': 'تحديث الحقل'
            }],
            'issues': [{'title': 'مراجعة', 'points': ['اشتراطات2.pdf صفحة 8 تحتاج تأكيدًا'], 'action': 'مراجعة', 'severity': 'medium'}],
            'summary': 'توجد مراجعة في اشتراطات1.pdf.', 'canProceed': True
        }
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(verification_payload, ensure_ascii=False)}}]
        }):
            verified = client.post('/api/visual-concept/plans-verify', headers=self._headers(self.token_a), json={
                'projectData': project_data
            })
        self.assertEqual(verified.status_code, 200, verified.get_json())
        verification = verified.get_json()['verification']
        serialized = json.dumps(verification, ensure_ascii=False)
        self.assertNotIn('اشتراطات1', serialized)
        self.assertNotIn('اشتراطات2', serialized)
        self.assertNotIn('صفحة', serialized)
        self.assertTrue(verification['issues'][0]['points'])
        self.assertEqual(verification['checks'][0]['suggestion'], 'غيّر القيمة في قسم المساحات من 60000 إلى 42072.72')

        with patch.object(module, '_visual_concept_render_plan_boundary_reference', return_value='/uploads/creative/parcel-ref.png'):
            boundary = client.post('/api/visual-concept/plans-boundary', headers=self._headers(self.token_a), json={
                'mode': 'manual', 'points': points, 'projectData': project_data,
                'plansWorkflow': {'verification': {'approved': True}}
            })
        self.assertEqual(boundary.status_code, 200, boundary.get_json())
        self.assertEqual(boundary.get_json()['referenceUrl'], '/uploads/creative/parcel-ref.png')
        self.assertEqual(len(boundary.get_json()['points']), 3)

        approved_rows = [{
            'building': 'Main Tower', 'floor_range': '26-52', 'component': 'Luxury Apartments',
            'units_per_floor': 9, 'floor_area_sqm': 1350, 'circulation': 'main core'}]
        gated = client.post('/api/visual-concept/plans-prompts', headers=self._headers(self.token_a), json={
            'projectData': project_data,
            'plansWorkflow': {
                'verification': {'approved': True},
                'boundary': {'approved': True, 'points': points, 'referenceUrl': '/uploads/creative/parcel-ref.png'}
            }
        })
        self.assertEqual(gated.status_code, 400, gated.get_json())
        self.assertEqual(gated.get_json()['error_code'], 'PLANS_DISTRIBUTION_REQUIRED')

        # sol adapts the fixed DRAWING REQUESTED bodies to the approved distribution;
        # the header + APPROVED DISTRIBUTION MODEL spec are spliced back verbatim, so
        # approved facts (name, floors, areas) cannot be dropped by the rewrite.
        adapted = {
            'site': "DRAWING REQUESTED — 'CONCEPTUAL SITE PLAN': adapted site body — no podium, no basement pocket, single approved tower. " * 2,
            'uses': "DRAWING REQUESTED — 'VERTICAL PROGRAM': adapted stack body — one approved band only. " * 3,
            'massing': "DRAWING REQUESTED — 'CONCEPTUAL MASSING': adapted massing body — one volume only. " * 3,
        }
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(adapted, ensure_ascii=False)}}]
        }) as adapt_call:
            prompts = client.post('/api/visual-concept/plans-prompts', headers=self._headers(self.token_a), json={
                'projectData': project_data,
                'plansWorkflow': {
                    'verification': {'approved': True},
                    'boundary': {'approved': True, 'points': points, 'referenceUrl': '/uploads/creative/parcel-ref.png'},
                    'distribution': {'approved': True, 'rows': approved_rows},
                }
            })
        self.assertEqual(prompts.status_code, 200, prompts.get_json())
        self.assertTrue(adapt_call.called)
        site_prompt = prompts.get_json()['prompts']['site']
        self.assertIn('اسم المشروع: The View', site_prompt)
        self.assertIn('APPROVED DISTRIBUTION MODEL', site_prompt)
        self.assertIn('adapted site body', site_prompt)
        self.assertIn('Luxury Apartments', site_prompt)
        self.assertIn('26-52', site_prompt)
        for kind in ('uses', 'massing'):
            self.assertIn('APPROVED DISTRIBUTION MODEL', prompts.get_json()['prompts'][kind])
        serialized_prompts = json.dumps(prompts.get_json()['prompts'], ensure_ascii=False)
        self.assertNotIn('اشتراطات1', serialized_prompts)
        self.assertNotIn('اشتراطات2', serialized_prompts)

        # When the adaptation call fails, the deterministic bodies still ship.
        with patch.object(module, 'call_openrouter_chat', side_effect=Exception('offline')):
            prompts = client.post('/api/visual-concept/plans-prompts', headers=self._headers(self.token_a), json={
                'projectData': project_data,
                'plansWorkflow': {
                    'verification': {'approved': True},
                    'boundary': {'approved': True, 'points': points, 'referenceUrl': '/uploads/creative/parcel-ref.png'},
                    'distribution': {'approved': True, 'rows': approved_rows},
                }
            })
        self.assertEqual(prompts.status_code, 200, prompts.get_json())
        self.assertIn('DRAWING REQUESTED', prompts.get_json()['prompts']['site'])

        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,CCCC') as image_call, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/site.png'), \
                patch.object(module, '_prepare_image_reference_for_model', side_effect=lambda url, tenant_id=None: f'data:image/png;base64,{str(url).rsplit("/", 1)[-1]}'):
            generated = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'plan_site', 'planKind': 'site', 'prompt': 'SITE PROMPT',
                'planBoundaryReferenceUrl': '/uploads/creative/parcel-ref.png',
                'plansWorkflow': {'verification': {'approved': True}, 'boundary': {'approved': True, 'points': points, 'referenceUrl': '/uploads/creative/parcel-ref.png'}, 'distribution': {'approved': True, 'rows': approved_rows}},
                'projectData': project_data
            })
        self.assertEqual(generated.status_code, 200, generated.get_json())
        self.assertTrue(any('parcel-ref.png' in str(item) for item in image_call.call_args.args[1]))

    def test_plans_distribution_is_proposed_checked_and_gates_prompts(self):
        module = self.application_module
        client = self.app.test_client()
        points = [
            {'point': 'P1', 'eastings': 511085.849, 'northings': 2392264.840},
            {'point': 'P2', 'eastings': 511189.416, 'northings': 2392298.825},
            {'point': 'P3', 'eastings': 511198.442, 'northings': 2392262.273},
        ]
        project_data = {
            'project_name': 'The View',
            'city': 'جدة',
            'croquis_land_area': 7012,
            'approved_floor_count': 30,
            'approved_coverage_ratio': 60,
            'survey_coordinates': points,
            'project_components_data': [
                {'name': 'مكاتب', 'useType': 'office', 'units': 20, 'builtArea': 4000},
                {'name': 'شقق', 'useType': 'residential', 'units': 12, 'builtArea': 1800},
            ],
        }
        workflow = {'verification': {'approved': True},
                    'boundary': {'approved': True, 'points': points, 'referenceUrl': '/x.png'}}

        # The proposal is gated on the approved verification like the rest of the flow.
        refused = client.post('/api/visual-concept/plans-distribution', headers=self._headers(self.token_a), json={
            'projectData': project_data, 'plansWorkflow': {}})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'PLANS_VERIFICATION_REQUIRED')

        proposed = {'rows': [
            {'building': 'المبنى الرئيسي', 'floor_range': '1-10', 'component': 'مكاتب',
             'units_per_floor': 2, 'floor_area_sqm': 400, 'circulation': 'بهو'},
            {'building': 'المبنى الرئيسي', 'floor_range': '11-15', 'component': 'شقق',
             'units_per_floor': 2.4, 'floor_area_sqm': 360, 'circulation': ''},
            {'building': 'المبنى الرئيسي', 'floor_range': 'B1', 'component': 'مواقف سيارات',
             'circulation': 'منحدر'},
        ], 'notes': ['فصل المداخل']}
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(proposed, ensure_ascii=False)}}]
        }):
            proposal = client.post('/api/visual-concept/plans-distribution', headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow})
        self.assertEqual(proposal.status_code, 200, proposal.get_json())
        distribution = proposal.get_json()['distribution']
        self.assertEqual(len(distribution['rows']), 3)
        totals = {row['component']: row for row in distribution['totals']}
        self.assertEqual(totals['مكاتب']['units'], 20)
        self.assertEqual(totals['مكاتب']['required_units'], 20)
        self.assertEqual(totals['شقق']['units'], 12)
        self.assertNotIn('notes', distribution)

        # The local re-check is deterministic — the same component claiming
        # overlapping ranges in one building is a hard conflict; different
        # components sharing a floor only get a soft confirmation note.
        overlapping = {'rows': [
            {'building': 'A', 'floor_range': '1-5', 'component': 'مكاتب'},
            {'building': 'A', 'floor_range': '4-9', 'component': 'المكاتب'},
        ]}
        with patch.object(module, 'call_openrouter_chat', side_effect=AssertionError('local check is deterministic')):
            checked = client.post('/api/visual-concept/plans-distribution-check', headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow, 'distribution': overlapping})
        self.assertEqual(checked.status_code, 200, checked.get_json())
        self.assertFalse(checked.get_json()['canProceed'])
        self.assertTrue(any(item['result'] == 'متعارض' for item in checked.get_json()['checks']))

        shared_floor = {'rows': [
            {'building': 'A', 'floor_range': 'G', 'component': 'سكني'},
            {'building': 'A', 'floor_range': 'G', 'component': 'تجاري'},
        ]}
        with patch.object(module, 'call_openrouter_chat', side_effect=AssertionError('local check is deterministic')):
            shared = client.post('/api/visual-concept/plans-distribution-check', headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow, 'distribution': shared_floor})
        self.assertEqual(shared.status_code, 200, shared.get_json())
        self.assertTrue(all(item['result'] != 'متعارض' for item in shared.get_json()['checks']))

        # mode=ai layers sol's conflict review on top of the deterministic pass.
        ai_review = {'issues': [{'title': 'المواقف', 'points': ['نقص مواقف'], 'suggestion': '', 'action': '', 'severity': 'low'}],
                     'canProceed': True}
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(ai_review, ensure_ascii=False)}}]
        }) as review_call:
            ai_checked = client.post('/api/visual-concept/plans-distribution-check', headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow, 'distribution': overlapping, 'mode': 'ai'})
        self.assertEqual(ai_checked.status_code, 200, ai_checked.get_json())
        self.assertTrue(review_call.called)
        self.assertEqual(ai_checked.get_json()['issues'][0]['title'], 'المواقف')

        # When sol is offline the proposal falls back to the deterministic inferred
        # distribution so the client still gets an editable table.
        with patch.object(module, 'call_openrouter_chat', side_effect=Exception('offline')):
            fallback = client.post('/api/visual-concept/plans-distribution', headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow})
        self.assertEqual(fallback.status_code, 200, fallback.get_json())
        self.assertTrue(fallback.get_json()['distribution']['rows'])

    def test_plans_distribution_totals_match_floor_scoped_study_rows(self):
        """The study stores components per floor («طابق أرضي - سكني» …) while the
        distribution groups per use — both sides aggregate on the base component
        before comparing. A mezzanine/مسروق is a slab inside the ground level,
        not a conflicting claim on floor 0, and basements never count in the FAR
        total."""
        module = self.application_module
        context = {'land_area': 9991, 'components': [
            {'name': 'طابق أرضي - سكني', 'units': 18, 'builtArea': 2027.95},
            {'name': 'طابق مسروق - سكني', 'units': 20, 'builtArea': 2200.0},
            {'name': 'طابق أول - سكني', 'units': 38, 'builtArea': 8532.85},
            {'name': 'طابق أرضي - تجاري', 'units': 16, 'builtArea': 1388.26},
            {'name': 'طابق مسروق - تجاري', 'builtArea': 640.74},
            {'name': 'طابق أرضي - خدمات', 'builtArea': 336.36},
            {'name': 'طابق أول - خدمات', 'builtArea': 2780.7},
            {'name': 'ملحق علوي - خدمات أخرى', 'builtArea': 500.0},
            {'name': 'طابق أرضي - مساحات أخرى', 'builtArea': 1223.47},
            {'name': 'طابق مسروق - مساحات أخرى', 'builtArea': 688.5},
            {'name': 'طابق أول - مساحات أخرى', 'builtArea': 868.73},
        ]}
        rows = [
            {'building': 'A', 'floor_range': 'أرضي', 'component': 'سكني',
             'units_per_floor': 18, 'floor_area_sqm': 2027.95},
            {'building': 'A', 'floor_range': 'ميزانين', 'component': 'سكني',
             'units_per_floor': 20, 'floor_area_sqm': 2200.0},
            {'building': 'A', 'floor_range': '1-2', 'component': 'سكني',
             'units_per_floor': 19, 'floor_area_sqm': 4266.425},
            {'building': 'A', 'floor_range': 'أرضي', 'component': 'تجاري',
             'units_per_floor': 16, 'floor_area_sqm': 1388.26},
            {'building': 'A', 'floor_range': 'ميزانين', 'component': 'تجاري',
             'floor_area_sqm': 640.7399999999},
            {'building': 'A', 'floor_range': 'أرضي', 'component': 'خدمات',
             'floor_area_sqm': 336.36},
            {'building': 'A', 'floor_range': '1', 'component': 'خدمات',
             'floor_area_sqm': 2780.7},
            {'building': 'A', 'floor_range': 'B1', 'component': 'مواقف سيارات',
             'floor_area_sqm': 5000},
        ]

        self.assertEqual(module._visual_concept_plan_floor_range('ميزانين'),
                         {'kind': 'mezzanine', 'lo': 0.5, 'hi': 0.5, 'count': 1})
        self.assertEqual(module._visual_concept_plan_floor_range('أرضي وميزانين')['kind'], 'ground')

        totals = {row['component']: row
                  for row in module._visual_concept_plan_distribution_totals(rows, context)}
        self.assertEqual(totals['سكني']['units'], 76)
        self.assertEqual(totals['سكني']['required_units'], 76)
        self.assertEqual(totals['سكني']['area'], 12760.8)
        self.assertEqual(totals['سكني']['required_area'], 12760.8)
        self.assertEqual(totals['سكني']['delta_area'], 0)
        # Long float tails are rounded before they reach the client.
        self.assertEqual(totals['تجاري']['area'], 2029.0)
        self.assertEqual(totals['تجاري']['required_area'], 2029.0)
        self.assertEqual(totals['خدمات']['required_area'], 3617.06)
        # Study rows with no distribution counterpart merge into one entry.
        self.assertEqual(totals['مساحات أخرى']['units'], 0)
        self.assertEqual(totals['مساحات أخرى']['required_area'], 2780.7)
        self.assertEqual(totals['مساحات أخرى']['delta_area'], -2780.7)

        checks = module._visual_concept_plan_distribution_checks(
            rows, list(totals.values()), context, {'floor_area_ratio': 1.2})
        # Ground + mezzanine for the same component is normal, not a conflict.
        self.assertFalse(any(item['result'] == 'متعارض' for item in checks))
        # FAR still fires — and the basement row is not part of its total.
        far_check = next(item for item in checks if 'معامل' in item['item'])
        self.assertIn('17906', far_check['detail'])
        self.assertNotIn('22906', far_check['detail'])

    def test_plans_distribution_repair_edits_only_flagged_rows(self):
        """The AI repair is surgical: the model receives the flagged row ids and
        may edit/merge/drop them, but any row no check named is restored
        verbatim even if the model rewrote it."""
        module = self.application_module
        client = self.app.test_client()
        points = [
            {'point': 'P1', 'eastings': 511085.849, 'northings': 2392264.840},
            {'point': 'P2', 'eastings': 511189.416, 'northings': 2392298.825},
            {'point': 'P3', 'eastings': 511198.442, 'northings': 2392262.273},
        ]
        project_data = {
            'project_name': 'The View',
            'croquis_land_area': 7012,
            'survey_coordinates': points,
            'project_components_data': [
                {'name': 'مكاتب', 'useType': 'office', 'units': 16, 'builtArea': 3200},
                {'name': 'شقق', 'useType': 'residential', 'units': 12, 'builtArea': 1800},
            ],
        }
        workflow = {'verification': {'approved': True},
                    'boundary': {'approved': True, 'points': points, 'referenceUrl': '/x.png'}}
        # r1/r2 overlap on the same component; r3 is clean and matches the study.
        distribution = {'rows': [
            {'id': 'r1', 'building': 'A', 'floor_range': '1-5', 'component': 'مكاتب',
             'units_per_floor': 2, 'floor_area_sqm': 400},
            {'id': 'r2', 'building': 'A', 'floor_range': '4-9', 'component': 'مكاتب',
             'units_per_floor': 1, 'floor_area_sqm': 300},
            {'id': 'r3', 'building': 'A', 'floor_range': '10-13', 'component': 'شقق',
             'units_per_floor': 3, 'floor_area_sqm': 450},
        ]}
        ai_reply = {'rows': [
            {'id': 'r1', 'building': 'A', 'floor_range': '1-5', 'component': 'مكاتب',
             'units_per_floor': 2, 'floor_area_sqm': 400},
            {'id': 'r2', 'building': 'A', 'floor_range': '6-9', 'component': 'مكاتب',
             'units_per_floor': 1, 'floor_area_sqm': 300},
            # The model was told not to touch r3 — it did anyway; the server reverts it.
            {'id': 'r3', 'building': 'A', 'floor_range': '10-13', 'component': 'شقق',
             'units_per_floor': 99, 'floor_area_sqm': 1},
        ]}
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(ai_reply, ensure_ascii=False)}}]
        }):
            repaired = client.post('/api/visual-concept/plans-distribution-repair',
                                   headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow,
                'distribution': distribution})
        self.assertEqual(repaired.status_code, 200, repaired.get_json())
        result_rows = {row['id']: row for row in repaired.get_json()['distribution']['rows']}
        self.assertEqual(result_rows['r2']['floor_range'], '6-9')
        self.assertEqual(result_rows['r3']['units_per_floor'], 3)
        self.assertEqual(result_rows['r3']['floor_area_sqm'], 450)
        self.assertFalse(any(item['result'] == 'متعارض'
                             for item in repaired.get_json()['distribution']['checks']))

        # A clean table short-circuits — no model call, nothing changes.
        clean = {'rows': [
            {'id': 'c1', 'building': 'A', 'floor_range': '1-8', 'component': 'مكاتب',
             'units_per_floor': 2, 'floor_area_sqm': 400},
            {'id': 'c2', 'building': 'A', 'floor_range': '11-15', 'component': 'شقق',
             'units_per_floor': 2.4, 'floor_area_sqm': 360},
        ]}
        with patch.object(module, 'call_openrouter_chat',
                          side_effect=AssertionError('no findings — model must not run')):
            untouched = client.post('/api/visual-concept/plans-distribution-repair',
                                    headers=self._headers(self.token_a), json={
                'projectData': project_data, 'plansWorkflow': workflow,
                'distribution': clean})
        self.assertEqual(untouched.status_code, 200, untouched.get_json())
        self.assertFalse(untouched.get_json()['repaired'])

    def test_plans_generate_sequentially_on_approved_plan_images(self):
        """The diagrams are drawn in order: uses needs the approved site plan,
        massing needs both — each previous image ships as a generation reference."""
        module = self.application_module
        client = self.app.test_client()
        points = [
            {'point': 'P1', 'eastings': 511085.849, 'northings': 2392264.840},
            {'point': 'P2', 'eastings': 511189.416, 'northings': 2392298.825},
            {'point': 'P3', 'eastings': 511198.442, 'northings': 2392262.273},
        ]
        project_data = {
            'project_name': 'The View',
            'croquis_land_area': 7012,
            'survey_coordinates': points,
            'project_components_data': [
                {'name': 'شقق', 'useType': 'residential', 'units': 12, 'builtArea': 1800}],
        }
        workflow = {
            'verification': {'approved': True},
            'boundary': {'approved': True, 'points': points,
                         'referenceUrl': '/uploads/creative/parcel-ref.png'},
            'distribution': {'approved': True, 'rows': [{
                'building': 'A', 'floor_range': '1-12', 'component': 'شقق',
                'units_per_floor': 1, 'floor_area_sqm': 150, 'circulation': ''}]},
        }

        # uses is gated on the approved site image; massing on both predecessors.
        for slot, images in (('plan_uses', {}),
                             ('plan_uses', {'uses': '/uploads/creative/uses.png'}),
                             ('plan_massing', {'site': '/uploads/creative/site.png'})):
            gated = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': slot, 'prompt': 'PROMPT', 'projectData': project_data,
                'plansWorkflow': workflow, 'planImages': images})
            self.assertEqual(gated.status_code, 400, (slot, images, gated.get_json()))
            self.assertEqual(gated.get_json()['error_code'], 'PLANS_ORDER_REQUIRED')

        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,U') as image_call, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/out.png'), \
                patch.object(module, '_prepare_image_reference_for_model',
                             side_effect=lambda url, tenant_id=None: 'ref:' + str(url)):
            uses = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'plan_uses', 'prompt': 'PROMPT', 'projectData': project_data,
                'plansWorkflow': workflow,
                'planImages': {'site': '/uploads/creative/site.png'}})
            self.assertEqual(uses.status_code, 200, uses.get_json())
            self.assertEqual(image_call.call_args.args[1], ['ref:/uploads/creative/site.png'])

            massing = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'plan_massing', 'prompt': 'PROMPT', 'projectData': project_data,
                'plansWorkflow': workflow,
                'planImages': {'site': '/uploads/creative/site.png',
                               'uses': '/uploads/creative/uses.png'}})
            self.assertEqual(massing.status_code, 200, massing.get_json())
            refs = image_call.call_args.args[1]
            self.assertEqual(refs[:2], ['ref:/uploads/creative/site.png',
                                        'ref:/uploads/creative/uses.png'])
            self.assertIn('ref:/uploads/creative/parcel-ref.png', refs)

    def test_sbc_evidence_search_is_bounded_and_scored(self):
        module = self.application_module
        records = [
            {'name': 'SBC201_AR2024.pdf', 'path': 'sbc.pdf', 'page': 9,
             'text': 'إشغال ومخارج ومواقف وارتفاع طوابق', 'has_table': False},
            {'name': 'SBC201_AR2024.pdf', 'path': 'sbc.pdf', 'page': 40,
             'text': 'نص لا علاقة له بالموضوع', 'has_table': False},
            # Some extracted spans arrive reversed; matching must still find them.
            {'name': 'SBC201_AR2024.pdf', 'path': 'sbc.pdf', 'page': 77,
             'text': 'فقاوم السيارات داخل المبنى', 'has_table': False},
        ]
        with patch.object(module, '_build_sbc_page_index', return_value=records), \
                patch.object(module, 'SBC_EVIDENCE_MAX_PAGES', 2):
            packet, warnings = module.search_sbc_evidence('مخارج', {})
        self.assertEqual(warnings, [])
        self.assertTrue(packet['matched'])
        self.assertEqual(packet['pages'][0], 9)
        self.assertIn(77, packet['pages'])
        self.assertNotIn('نص لا علاقة', packet['context'])
        self.assertLessEqual(len(packet['context']), module.SBC_EVIDENCE_MAX_CHARS + 200)

    def test_sbc_evidence_missing_file_warns(self):
        module = self.application_module
        with patch.object(module, '_build_sbc_page_index', return_value=[]):
            packet, warnings = module.search_sbc_evidence('إشغال', {})
        self.assertFalse(packet['matched'])
        self.assertEqual(packet['pages'], [])
        self.assertTrue(any('كود البناء' in warning for warning in warnings))

    def test_regulation_facts_never_fall_back_to_project_data(self):
        """A missing documented value must surface as غير متوفر — the project
        can never be its own regulatory source."""
        module = self.application_module
        facts = module._visual_concept_plan_regulation_facts({
            'coverage_ratio': 60, 'boundary_lengths': '120م', 'setbacks': '5م'})
        self.assertNotIn('coverage_ratio', facts)
        self.assertNotIn('boundary_lengths', facts)
        self.assertNotIn('setbacks', facts)

    def test_plans_verify_uses_saudi_code_evidence_and_digest(self):
        module = self.application_module
        client = self.app.test_client()
        project_data = {
            'project_name': 'SBC Tower',
            'city': 'جدة',
            'croquis_land_area': 3000,
            'approved_coverage_ratio': 55,
            'land_documents_analysis': {'parcels': [{
                'zoning_code': 'س ع', 'croquis_land_area': 3000,
                'coverage_ratio': '65%', 'table_floors': '4',
                'directions': {'north': {'street_width_m': 20}},
            }]},
        }
        captured = {}

        def fake_chat(system_prompt, user_prompt, **kwargs):
            captured['user'] = user_prompt
            return {'choices': [{'message': {'content': json.dumps(
                {'checks': [], 'issues': [], 'summary': 'ok', 'canProceed': True},
                ensure_ascii=False)}}]}

        sbc_packet = {
            'context': '--- SBC201_AR2024.pdf — صفحة 9 — score=40 ---\nمتطلبات الإشغال والمخارج',
            'pages': [9], 'matched': True,
        }
        with patch.object(module, 'search_sbc_evidence', return_value=(sbc_packet, [])) as sbc_search, \
                patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
            response = client.post('/api/visual-concept/plans-verify',
                                   headers=self._headers(self.token_a),
                                   json={'projectData': project_data})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(sbc_search.called)
        evidence = response.get_json()['evidence']
        self.assertTrue(evidence['sbc_matched'])
        self.assertEqual(evidence['sbc_pages'], [9])
        payload = json.loads(captured['user'].split(':\n', 1)[1].rsplit('\nرتّب', 1)[0])
        regulatory = payload['regulatory_facts']
        self.assertIn('متطلبات الإشغال والمخارج', regulatory['saudi_building_code'])
        self.assertEqual(regulatory['regulatory_zone'], 'س ع')
        self.assertIn('كود البناء السعودي', regulatory['regulatory_sources'])
        # The digest's authoritative value wins over the parcel's differing
        # number, and the difference is recorded for review — not silently kept.
        self.assertIn('75%', regulatory['coverage_ratio'])
        self.assertNotIn('55', str(regulatory.get('coverage_ratio')))
        self.assertTrue(any('التغطية' in point and 'مستندات الأرض' in point
                            for point in regulatory['existing_review_points']))

    def test_plans_verify_surfaces_missing_saudi_code(self):
        module = self.application_module
        client = self.app.test_client()
        with patch.object(module, 'search_sbc_evidence',
                          return_value=({'context': '', 'pages': [], 'matched': False},
                                        ['كود البناء السعودي غير متاح — لا يوجد ملف قابل للبحث'])), \
                patch.object(module, 'call_openrouter_chat', return_value={
                    'choices': [{'message': {'content': json.dumps(
                        {'checks': [], 'issues': [], 'summary': '', 'canProceed': True})}}]}):
            response = client.post('/api/visual-concept/plans-verify',
                                   headers=self._headers(self.token_a),
                                   json={'projectData': {'project_name': 'X'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()['evidence']['sbc_matched'])
        titles = [issue['title'] for issue in response.get_json()['verification']['issues']]
        self.assertIn('كود البناء السعودي', titles)

    def test_executive_content_section_generates_each_block_from_existing_facts(self):
        import executive_content

        facts = {
            'projectName': 'ذا فيو',
            'projectType': ['سكني', 'فندقي'],
            'projectIdea': 'منتجع شاطئي',
            'targetAudience': ['عائلات', 'سياح وزوار'],
            'city': 'جدة',
            'allowedUses': 'سكني فندقي',
            'croquisLandArea': '7012',
            'timelineStartDate': '2026-02',
            'timelineStartYear': '2026',
            'timelineStages': [{'name': 'التصميم', 'year': '1', 'quarter': 'Q1'}],
            'financialIndicators': {'roi': '12%'},
            'marketSummary': {'decision': 'فرصة واعدة بشروط'},
            'marketSwot': {'strengths': 'موقع بحري'},
        }
        ready, missing = executive_content.block_ready('brief', facts)
        self.assertTrue(ready)
        self.assertEqual(missing, [])
        blocked, needed = executive_content.block_ready('opportunity', {'projectName': 'ذا فيو', 'projectType': 'سكني'})
        self.assertFalse(blocked)
        self.assertIn('financial', needed)
        self.assertIn('summary', [item['key'] for item in executive_content.BLOCKS])
        self.assertNotIn('swot', [item['key'] for item in executive_content.BLOCKS])
        parsed = executive_content.parse_generated_block('summary', {
            'sections': [
                {'heading': 'البيانات الأساسية', 'text': 'منتجع شاطئي في جدة'},
                {'heading': 'دراسة السوق', 'text': 'فرصة واعدة بشروط'},
            ]
        })
        self.assertIn('البيانات الأساسية', parsed)
        self.assertIn('منتجع شاطئي في جدة', parsed)
        self.assertIn('\n\n', parsed)
        compact = executive_content.compact_facts(facts)
        self.assertEqual(compact['allowedUses'], 'سكني فندقي')
        self.assertEqual(compact['timelineStartDate'], '2026-02')
        self.assertEqual(compact['timelineStages'][0]['name'], 'التصميم')
        self.assertEqual(compact['marketSwot']['strengths'], 'موقع بحري')
        summary_facts = {
            **facts,
            'generatedBlocks': {'brief': 'نص السكشن فقط', 'risks': 'خطر من السكشن'},
            'marketOneBlockSummary': 'ملخص سوق المشروع من الدراسة',
        }
        summary_compact = executive_content.compact_facts(summary_facts, for_block='summary')
        self.assertEqual(summary_compact['generatedBlocks'], {})
        self.assertEqual(summary_compact['marketOneBlockSummary'], 'ملخص سوق المشروع من الدراسة')
        other_compact = executive_content.compact_facts(summary_facts, for_block='brief')
        self.assertEqual(other_compact['generatedBlocks']['brief'], 'نص السكشن فقط')
        parsed_risks = executive_content.parse_generated_block('risks', {
            'items': [
                {'risk': 'ارتفاع تكلفة التنفيذ', 'mitigation': 'تثبيت عقود المقاولين'},
                {'risk': 'تأخر التصاريح', 'mitigation': ''},
            ]
        })
        self.assertIn('الخطر: ارتفاع تكلفة التنفيذ', parsed_risks)
        self.assertIn('المعالجة: تثبيت عقود المقاولين', parsed_risks)
        self.assertIn('الخطر: تأخر التصاريح', parsed_risks)
        summary_ready, summary_missing = executive_content.block_ready('summary', facts)
        self.assertTrue(summary_ready)
        self.assertEqual(summary_missing, [])

        index_source = read_frontend_text()
        app_source = read_module_source('app.py')
        module_source = (ROOT / 'executive_content.py').read_text(encoding='utf-8')
        self.assertIn("function addExecutiveContentSection(form, before)", index_source)
        self.assertIn("addExecutiveContentSection(form);", index_source)
        self.assertIn("id = 'section-executive-content'", index_source)
        self.assertIn('data-key="executive_content"', index_source)
        self.assertIn("function generateExecutiveContentBlock(key)", index_source)
        self.assertIn("api('POST', '/api/executive-content/generate'", index_source)
        self.assertIn("createProjectSectionHeader('section-executive-content', 'المحتوى التنفيذي')", index_source)
        self.assertIn("function collectExecutiveContentFacts()", index_source)
        self.assertIn("function collectExecutiveTeamFacts()", index_source)
        self.assertIn("function collectExecutiveTimelineFacts()", index_source)
        self.assertNotIn("بيانات مرتبطة من الأقسام السابقة", index_source)
        self.assertNotIn("underConstruction: true", index_source)
        self.assertNotIn('executiveSwot_', index_source)
        self.assertNotIn("{ key: 'swot', label: 'تحليل SWOT' }", index_source)
        self.assertIn("def api_generate_executive_content():", app_source)
        self.assertIn('EXECUTIVE_SUMMARY_MAX_TOKENS', app_source)
        self.assertIn('لا تخترع', module_source)
        self.assertIn('الملخص التنفيذي الشامل', module_source)
        self.assertIn('بيانات المشروع', module_source)
        self.assertIn('طريقة معالجته', module_source)
        self.assertIn("'output': 'document'", module_source)
        self.assertIn("'output': 'risks'", module_source)
        self.assertIn('for_block != \'summary\'', module_source)
        self.assertIn('marketOneBlockSummary', index_source)

        client = self.app.test_client()
        refused = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
            'block': 'opportunity',
            'facts': {'projectName': 'ذا فيو', 'projectType': 'سكني'},
        })
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertIn('استكمل', refused.get_json()['error'])

        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': '{"text":"نبذة من الفكرة فقط"}'}}]}), \
             patch.object(self.application_module, 'extract_chat_content', return_value='{"text":"نبذة من الفكرة فقط"}'):
            generated = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'brief',
                'facts': facts,
            })
        self.assertEqual(generated.status_code, 200, generated.get_json())
        self.assertEqual(generated.get_json()['text'], 'نبذة من الفكرة فقط')

        summary_payload = '{"text":"البيانات الأساسية\\nمنتجع شاطئي\\n\\nالدراسة المالية\\nالعائد 12%"}'
        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': summary_payload}}]}) as chat_call, \
             patch.object(self.application_module, 'extract_chat_content', return_value=summary_payload):
            summary = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'summary',
                'facts': facts,
            })
        self.assertEqual(summary.status_code, 200, summary.get_json())
        self.assertIn('البيانات الأساسية', summary.get_json()['text'])
        self.assertEqual(chat_call.call_args.kwargs.get('max_tokens'), self.application_module.EXECUTIVE_SUMMARY_MAX_TOKENS)

        parsed_dict = executive_content.parse_generated_block('summary', {'البيانات الأساسية': 'منتجع', 'الموقع': 'جدة'})
        self.assertIn('البيانات الأساسية\nمنتجع', parsed_dict)
        self.assertIn('الموقع\nجدة', parsed_dict)

        raw_md = 'البيانات الأساسية\nمشروع ذا فيو في جدة\n\nالدراسة المالية\nعائد استثماري متميز'
        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': raw_md}}]}), \
             patch.object(self.application_module, 'extract_chat_content', return_value=raw_md):
            summary_raw = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'summary',
                'facts': {'projectName': 'ذا فيو', 'projectType': 'سكني'},
            })
        self.assertEqual(summary_raw.status_code, 200, summary_raw.get_json())
        self.assertIn('مشروع ذا فيو في جدة', summary_raw.get_json()['text'])
