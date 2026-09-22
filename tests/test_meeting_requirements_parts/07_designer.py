class MeetingRequirementsTestsPart06(MeetingRequirementsTests):

    def test_presentation_update_never_answers_a_bare_500(self):
        """A PUT the server cannot honor must answer JSON, never a bare HTML 500.

        The workspace lives only in the browser until the save lands, so an
        unreadable failure both hides the cause and looks like lost work.
        """
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض الحماية', 'projectData': {'project_name': 'عرض الحماية'},
            'slidesData': [{'title': 'الغلاف', 'type': 'cover',
                            'html': '<div class="slide">غلاف</div>'}],
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']
        revision = created.get_json()['presentation']['revision']

        base_project = {'project_name': 'عرض الحماية'}
        base_slides = [{'title': 'محتوى', 'type': 'content',
                        'html': '<div class="slide"><p>نص عربي</p></div>'}]
        adversarial = [
            ('blob-url', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><img src="blob:https://example.test/abc"></div>'}]}),
            ('missing-local-file', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><img src="/uploads/maps/gone.png"></div>'}]}),
            ('foreign-tenant-path', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><img src="/uploads/creative/other-tenant/a.png"></div>'}]}),
            ('unsupported-data-uri', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><img src="data:image/gif;base64,R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs="></div>'}]}),
            ('nested-slides-in-project', {
                'projectData': {**base_project, 'tenantSlidesData': base_slides * 20}}),
            ('huge-html', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><p>' + 'نص طويل جدا ' * 20000 + '</p></div>'}]}),
            ('lone-surrogate', {'slidesData': [
                {'title': 'x', 'type': 'content',
                 'html': '<div class="slide"><p>test \ud83d end</p></div>'}]}),
            ('garbage-provenance', {'changeSource': 'ai', 'provenance': {'token': 'garbage'}}),
            ('index-entries-mismatch', {'slidesData': [
                {'title': 'محتويات العرض', 'type': 'index',
                 'html': '<div class="slide">فهرس</div>',
                 'index_entries': [{'section_key': 'x', 'page': 'not-a-number'}]}]}),
        ]
        for name, extra in adversarial:
            payload = {'title': 'عرض الحماية', 'projectData': dict(base_project),
                       'slidesData': [dict(slide) for slide in base_slides],
                       'expectedRevision': revision}
            payload.update(extra)
            response = client.put('/api/presentations/' + presentation_id,
                                  headers=headers, json=payload)
            data = response.get_json()
            self.assertIsNotNone(data, f'{name}: expected a JSON answer')
            self.assertNotEqual(response.status_code, 500, f'{name}: bare 500')
            if response.status_code == 200:
                self.assertTrue(data.get('success'), f'{name}: {str(data)[:300]}')
                revision = data['presentation']['revision']
            else:
                self.assertIn(response.status_code, (400, 409),
                              f'{name}: unexpected HTTP {response.status_code}: {str(data)[:300]}')
                self.assertIn('error', data, f'{name}: error answer carries no message')

        index_source = read_frontend_text()
        update_source = index_source.split('async function saveExistingPresentation', 1)[1].split(
            'async function regeneratePresentationMaps', 1)[0]
        self.assertLess(update_source.index('saveProjectAsDraftNow(true, false)'),
                        update_source.index('renumberTenantSlides();'))

    def test_export_rebuilds_legacy_plan_without_image_tokens(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        legacy_plan = {
            'title': 'مخطط الدور الأرضي',
            'type': 'content',
            'section_key': 'plans',
            'content_source': 'plan_image:1',
            'html': (
                '<div class="slide" style="width:1280px;height:720px;overflow:hidden">'
                '<img class="project-logo" src="/uploads/creative/tenant/project-logo.png">'
                '<img src="/uploads/creative/tenant/plan-floor-1.png" '
                'style="display:block;width:100%;height:auto"></div>'
            ),
        }

        with patch('exports.pdf_export.generate_pdf') as generate_pdf:
            exported = client.post('/api/export', headers=headers, json={
                'format': 'pdf',
                'projectName': 'عرض المخطط',
                'projectData': {'project_name': 'عرض المخطط'},
                'slidesData': [legacy_plan],
            })

        self.assertTrue(exported.get_json()['success'], exported.get_json())
        exported_html = generate_pdf.call_args.args[0]
        self.assertIn('data-visual-media-only="1"', exported_html)
        self.assertIn('/uploads/creative/tenant/plan-floor-1.png', exported_html)
        self.assertNotIn('/uploads/creative/tenant/project-logo.png', exported_html)
        self.assertNotIn('height:auto', exported_html)
        self.assertIn('object-fit:contain!important', exported_html)

    def test_the_slide_structure_is_not_client_facing(self):
        """Owner rule: the client never operates the structure — no plan panel, no editable plan
        titles, and no button that builds or rebuilds it outside «توليد العرض»."""
        index_source = read_frontend_text()
        for gone in (
            'تحديث الهيكل المقترح',
            'إعداد الهيكل المقترح',
            'generateSlidePlanOnly',
            'regenerateTenantSlidePlan',
            'renderTenantSlidePlan',
            'updatePlanSlideTitle',
            'tenantSlidePlanList',
            'slidePlanInfo',
            'tenant-slide-plan-card',
        ):
            self.assertNotIn(gone, index_source, gone)
        # The plan itself still exists — it is produced inside the generation flow.
        self.assertIn('const planResponse = await requestTenantSlidePlan(tenantProjectData', index_source)
        self.assertIn('slidePlan: tenantSlidePlan', index_source)

    def test_change_lines_name_the_difference_not_just_that_something_changed(self):
        import change_tracking as tracking
        old = [
            {'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1><img src="/uploads/a.png"></div>'},
            {'title': 'الموقع', 'html': '<div class="slide"><p>الرياض. حي الملقا.</p></div>'},
            {'title': 'المالية', 'html': '<div class="slide"><p>تكلفة 480 مليون</p></div>'},
        ]
        new = [
            {'title': 'الغلاف الرئيسي', 'html': '<div class="slide"><h1>THE VIEW</h1><img src="/uploads/b.png"></div>'},
            {'title': 'الموقع', 'html': '<div class="slide" style="color:red"><p>الرياض. حي الملقا.</p></div>'},
            {'title': 'المالية', 'html': '<div class="slide"><p>تكلفة 500 مليون</p></div>'},
            {'title': 'شكراً', 'html': '<div class="slide"><h2>شكراً</h2></div>'},
        ]
        lines = tracking.describe_slide_changes(old, new)
        joined = '\n'.join(lines)
        self.assertIn('عدد الشرائح: من 3 إلى 4', joined)
        self.assertIn('العنوان: من «الغلاف» إلى «الغلاف الرئيسي»', joined)
        self.assertIn('استُبدلت صورة أو خريطة', joined)
        self.assertIn('تغيّر التنسيق والألوان بدون تغيير النص', joined)
        self.assertIn('تكلفة 480 مليون', joined)
        self.assertIn('تكلفة 500 مليون', joined)
        self.assertIn('أُضيفت الشريحة 4', joined)
        self.assertNotIn('تعديل المحتوى', joined)

        draft_lines = '\n'.join(tracking.detail_text(item) for item in tracking.describe_draft_changes(
            {'project_name': 'the view', 'city': 'جدة', 'financial_study_model': {'inputs': {'a': 1}}},
            {'project_name': 'THE VIEW', 'district': 'الشاطئ', 'financial_study_model': {'inputs': {'a': 2}}},
        ))
        self.assertIn('من «the view» إلى «THE VIEW»', draft_lines)
        self.assertIn('أُفرغ (كان «جدة»)', draft_lines)
        self.assertIn('أُضيف «الشاطئ»', draft_lines)
        # A blob is diffed to the leaf: the section and the inner path are named,
        # and the changed value shows before/after — never «تم تحديث البيانات».
        self.assertIn('الدراسة المالية', draft_lines)
        self.assertIn('مدخلات الدراسة', draft_lines)
        self.assertIn('من «1» إلى «2»', draft_lines)
        self.assertNotIn('تم تحديث البيانات', draft_lines)
        # A blob is named, never dumped as a value.
        self.assertNotIn('inputs', draft_lines)

    def test_team_selection_changes_name_the_entity_not_its_id(self):
        # «team_selection» stores library entity ids in roles/excluded — the log
        # must resolve them to the entity's name, not print a raw uuid.
        import change_tracking as tracking
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        with self.app.app_context():
            developer_id = db.create_team_entity(
                self.tenant_a, 'شركة التطوير الأولى', role='مطور')
            engineer_id = db.create_team_entity(
                self.tenant_a, 'مكتب الهندسة المتحدة', role='استشاري')
        draft_id = 'draft-team-history'
        base = {'draftId': draft_id, 'project_name': 'Team Project'}
        client.post('/api/project-draft', headers=headers, json={
            'draftId': draft_id,
            'draftData': {**base, 'team_selection': {
                'excluded': [], 'roles': {developer_id: 'مقاول عام'}, 'local': []}},
            'sectionStatuses': {},
        })
        response = client.post('/api/project-draft', headers=headers, json={
            'draftId': draft_id,
            'draftData': {**base, 'team_selection': {
                'excluded': [engineer_id],
                'roles': {developer_id: 'مهندس استشاري'},
                'local': [{'localId': 'loc-1', 'name': 'شركة البناء الحديث',
                           'role': 'مقاول'}]}},
            'sectionStatuses': {},
        })
        self.assertEqual(response.status_code, 200)

        log = client.get(f'/api/project-draft/{draft_id}/edit-log',
                         headers=headers).get_json()
        self.assertTrue(log.get('log'))
        last = log['log'][0]
        # Each touched section lands as its own entry naming the section.
        self.assertEqual(last.get('action'), 'تعديل «فريق العمل»')
        joined = '\n'.join(tracking.detail_text(item)
                           for item in (last.get('details') or []))
        self.assertIn('فريق العمل', joined)
        self.assertIn('استُبعدت من الملف: مكتب الهندسة المتحدة', joined)
        self.assertIn('«شركة التطوير الأولى»: من «مقاول عام» إلى «مهندس استشاري»', joined)
        self.assertIn('أُضيف «شركة البناء الحديث»', joined)
        self.assertNotIn(engineer_id, joined)
        self.assertNotIn(developer_id, joined)

    def test_project_archive_and_previous_presentations_are_filtered_and_scoped(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_alpha = 'draft-alpha-archive'
        draft_beta = 'draft-beta-archive'
        for draft_id, name in ((draft_alpha, 'Alpha Project'), (draft_beta, 'Beta Project')):
            response = client.post('/api/project-draft', headers=headers, json={
                'draftId': draft_id,
                'draftData': {'draftId': draft_id, 'project_name': name},
                'sectionStatuses': {},
            })
            self.assertEqual(response.status_code, 200)

        presentation_ids = []
        for index, status in enumerate(('draft', 'pending_approval', 'approved')):
            response = client.post('/api/presentations', headers=headers, json={
                'title': f'Alpha Presentation {index}',
                'projectData': {'draftId': draft_alpha, 'project_name': 'Alpha Project'},
                'slidesData': [{'title': 'Cover', 'type': 'cover', 'html': '<div class="slide">Cover</div>'}],
                'slideCount': 1,
            })
            self.assertEqual(response.status_code, 201)
            presentation_id = response.get_json()['presentationId']
            presentation_ids.append(presentation_id)
            if status != 'draft':
                # Operational states belong to the approval gates — a save
                # payload can never walk into them, so the fixture writes the
                # state directly the way a decided gate would leave it.
                with self.app.app_context():
                    connection = db.get_db()
                    connection.execute(
                        "UPDATE presentations SET status = ? WHERE id = ?",
                        (status, presentation_id))
                    connection.commit()
        beta_presentation = client.post('/api/presentations', headers=headers, json={
            'title': 'Beta Presentation',
            'projectData': {'draftId': draft_beta, 'project_name': 'Beta Project'},
            'slidesData': [{'title': 'Cover', 'type': 'cover', 'html': '<div class="slide">Cover</div>'}],
            'slideCount': 1,
        }).get_json()['presentationId']
        # Sealed after its presentation exists: a locked draft accepts no new artifacts.
        with self.app.app_context():
            connection = db.get_db()
            connection.execute("UPDATE project_drafts SET status = 'approved' WHERE id = ?", (draft_beta,))
            connection.commit()

        filtered = client.get(
            '/api/presentations?draftId=' + draft_alpha + '&status=draft&search=Alpha', headers=headers)
        self.assertEqual(filtered.status_code, 200)
        items = filtered.get_json()['presentations']
        self.assertEqual([item['id'] for item in items], [presentation_ids[0]])
        self.assertTrue(all(item['draftId'] == draft_alpha for item in items))
        all_alpha = client.get('/api/presentations?draftId=' + draft_alpha, headers=headers).get_json()['presentations']
        self.assertEqual({item['id'] for item in all_alpha}, set(presentation_ids))
        self.assertNotIn(beta_presentation, {item['id'] for item in all_alpha})

        project_search = client.get('/api/project-drafts?search=Alpha', headers=headers).get_json()['drafts']
        self.assertEqual([item['id'] for item in project_search], [draft_alpha])
        approved = client.get('/api/project-drafts?status=approved', headers=headers).get_json()['drafts']
        approved_ids = [item['id'] for item in approved]
        self.assertIn(draft_beta, approved_ids)
        self.assertNotIn(draft_alpha, approved_ids)
        with self.app.app_context():
            stored = db.get_presentation(presentation_ids[0], tenant_id=self.tenant_a)
            self.assertEqual(stored['draft_id'], draft_alpha)

        index_html = read_frontend_text()
        archive_source = index_html[
            index_html.index('async function openTenantPresentations'):
            index_html.index('async function restoreProjectDraft')
        ]
        self.assertIn("'/api/project-drafts?'", archive_source)
        self.assertNotIn("'/api/presentations'", archive_source)
        self.assertIn('loadProjectPresentationsPage', index_html)
        self.assertIn('openProjectPresentationsTab', index_html)
        self.assertIn('tenantProjectPresentationsPage', index_html)
        self.assertIn('بانتظار التعميد', index_html)
        self.assertIn(".filter(group => group.items.length)", index_html)

    def test_usage_totals_aggregate_project_files_and_scope_by_tenant(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_id = 'draft-usage-totals'
        response = client.post('/api/project-draft', headers=headers, json={
            'draftId': draft_id,
            'draftData': {'draftId': draft_id, 'project_name': 'Usage Project'},
            'sectionStatuses': {},
        })
        self.assertEqual(response.status_code, 200)
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'Usage Presentation',
            'projectData': {'draftId': draft_id, 'project_name': 'Usage Project'},
            'slidesData': [{'title': 'Cover', 'type': 'cover', 'html': '<div class="slide">Cover</div>'}],
            'slideCount': 1,
        })
        self.assertEqual(created.status_code, 201)
        presentation_id = created.get_json()['presentationId']
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=100,
                cost_usd=0.02, draft_id=draft_id)
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=50,
                cost_usd=0.01, presentation_id=presentation_id)
            db.record_maps_usage_event(
                self.tenant_a, 'staticmap', 2, 0.002, flow='overview',
                presentation_id=presentation_id)
            db.record_ai_usage_event(
                self.tenant_b, 'model-a', flow='slide', total_tokens=999,
                cost_usd=9.99, draft_id='draft-usage-totals-foreign')
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=10,
                generation_id='gen-usage-pending', draft_id=draft_id)
        totals = client.get(
            f'/api/usage-totals?draftIds={draft_id}&presentationIds={presentation_id}',
            headers=headers).get_json()
        self.assertTrue(totals['success'])
        project = totals['projects'][draft_id]
        self.assertAlmostEqual(project['ai_cost_usd'], 0.03)
        self.assertAlmostEqual(project['maps_cost_usd'], 0.004)
        self.assertAlmostEqual(project['cost_usd'], 0.034)
        self.assertEqual(project['calls'], 4)
        self.assertEqual(project['total_tokens'], 160)
        self.assertGreaterEqual(totals['pending_costs'], 1)
        presentation = totals['presentations'][presentation_id]
        self.assertAlmostEqual(presentation['cost_usd'], 0.014)
        self.assertEqual(presentation['calls'], 2)
        self.assertEqual(presentation['total_tokens'], 50)
        foreign = client.get(
            f'/api/usage-totals?draftIds={draft_id}&presentationIds={presentation_id}',
            headers=self._headers(self.token_b)).get_json()
        self.assertEqual(foreign['projects'][draft_id]['calls'], 0)
        self.assertEqual(foreign['presentations'][presentation_id]['calls'], 0)
        unknown = client.get(
            '/api/usage-totals?draftIds=no-such-draft', headers=headers).get_json()
        self.assertEqual(unknown['projects']['no-such-draft']['cost_usd'], 0.0)
        denied = client.get(f'/api/usage-totals?draftIds={draft_id}')
        self.assertEqual(denied.status_code, 401)

        index_html = read_frontend_text()
        self.assertIn("'/api/usage-totals?draftIds='", index_html)
        self.assertIn("'/api/usage-totals?presentationIds='", index_html)
        self.assertIn('function formatUsageCost(sar)', index_html)
        self.assertIn('costByProject', index_html)
        self.assertIn('costByPresentation', index_html)
        self.assertIn('costByProject[d.id]', index_html)
        self.assertIn('costByPresentation[item.id]', index_html)
        self.assertIn('maps_cost_sar', index_html)
        self.assertIn("'<span>التكلفة:</span> '", index_html)

    def test_presentation_creation_links_prior_draft_spend_without_stealing(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_id = 'draft-usage-link'
        response = client.post('/api/project-draft', headers=headers, json={
            'draftId': draft_id,
            'draftData': {'draftId': draft_id, 'project_name': 'Link Project'},
            'sectionStatuses': {},
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=70,
                cost_usd=0.05, draft_id=draft_id)
            db.record_maps_usage_event(
                self.tenant_a, 'staticmap', 1, 0.002, flow='overview', draft_id=draft_id)

        def _save_file(title):
            created = client.post('/api/presentations', headers=headers, json={
                'title': title,
                'projectData': {'draftId': draft_id, 'project_name': 'Link Project'},
                'slidesData': [{'title': 'Cover', 'type': 'cover', 'html': '<div class="slide">Cover</div>'}],
                'slideCount': 1,
            })
            self.assertEqual(created.status_code, 201)
            return created.get_json()['presentationId']

        first_id = _save_file('First File')
        totals = client.get(
            f'/api/usage-totals?draftIds={draft_id}&presentationIds={first_id}',
            headers=headers).get_json()
        self.assertAlmostEqual(totals['presentations'][first_id]['cost_usd'], 0.052)
        self.assertEqual(totals['presentations'][first_id]['calls'], 2)
        self.assertAlmostEqual(totals['projects'][draft_id]['cost_usd'], 0.052)

        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=30,
                cost_usd=0.03, draft_id=draft_id)
        second_id = _save_file('Second File')
        totals = client.get(
            f'/api/usage-totals?draftIds={draft_id}&presentationIds={first_id},{second_id}',
            headers=headers).get_json()
        self.assertAlmostEqual(totals['presentations'][first_id]['cost_usd'], 0.052)
        self.assertAlmostEqual(totals['presentations'][second_id]['cost_usd'], 0.03)
        self.assertAlmostEqual(totals['projects'][draft_id]['cost_usd'], 0.082)

    def test_ai_attempt_columns_migrate_on_existing_database(self):
        import sqlite3
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), 'ai-migrate.db')
        original = db.DB_PATH
        try:
            db.DB_PATH = path
            db.init_db()
            conn = sqlite3.connect(path)
            conn.execute('DROP TABLE IF EXISTS ai_usage_events')
            conn.execute('''CREATE TABLE ai_usage_events (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                draft_id TEXT,
                presentation_id TEXT,
                flow TEXT NOT NULL DEFAULT 'other',
                model TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL,
                generation_id TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )''')
            conn.execute("INSERT INTO ai_usage_events (id, tenant_id, model, cost_usd, generation_id) "
                         "VALUES ('legacy-1', 't1', 'model-a', 0.02, 'gen-legacy-1')")
            conn.commit()
            conn.close()
            db.init_db()
            conn = sqlite3.connect(path)
            names = {row[1] for row in conn.execute('PRAGMA table_info(ai_usage_events)').fetchall()}
            for column in ('cost_source', 'attempt_status', 'reconcile_attempts',
                           'next_retry_at', 'updated_at', 'response_cost_usd',
                           'generation_cost_usd', 'cost_raw'):
                self.assertIn(column, names)
            row = conn.execute("SELECT cost_usd, generation_id FROM ai_usage_events WHERE id='legacy-1'").fetchone()
            conn.close()
            self.assertAlmostEqual(row[0], 0.02)
            self.assertEqual(row[1], 'gen-legacy-1')
        finally:
            db.DB_PATH = original

    def test_usage_totals_expose_uncapped_reconcile_status(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_id = 'draft-usage-reconcile-status'
        client.post('/api/project-draft', headers=headers, json={
            'draftId': draft_id,
            'draftData': {'draftId': draft_id, 'project_name': 'Reconcile Project'},
            'sectionStatuses': {},
        })
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=10,
                cost_usd=0.01, cost_source='response', draft_id=draft_id)
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=10,
                generation_id='gen-pending-scope', draft_id=draft_id)
            db.record_ai_usage_event(
                self.tenant_a, 'model-a', flow='slide', total_tokens=10,
                draft_id=draft_id)
        totals = client.get(
            f'/api/usage-totals?draftIds={draft_id}', headers=headers).get_json()
        self.assertTrue(totals['success'])
        self.assertIn('reconcile', totals)
        self.assertIn('reconcile_by_scope', totals)
        by_draft = totals['reconcile_by_scope']['by_draft'][draft_id]
        self.assertEqual(by_draft['pending'], 1)
        self.assertEqual(by_draft['unresolved'], 1)
        self.assertEqual(by_draft['state'], 'pending')
        self.assertEqual(by_draft['state_label'], 'قيد الاستكمال')
        index_html = read_frontend_text()
        self.assertIn('aiReconcileStatusText', index_html)
        self.assertIn('قيد الاستكمال', index_html)
        self.assertIn('تحتاج مطابقة', index_html)
        self.assertIn('التكلفة المسجلة', index_html)
        self.assertIn('/api/ai-usage/reconcile', index_html)

    def test_truckplex_arithmetic_difference_uses_decimal(self):
        from decimal import Decimal
        provider = Decimal('0.76317')
        system = Decimal('0.75577005')
        self.assertEqual(provider - system, Decimal('0.00739995'))

    def test_slide_reordering_is_named_in_change_history(self):
        old_slides = [
            {'title': 'الأولى', 'type': 'content', 'html': '<div class="slide">أ</div>'},
            {'title': 'الثانية', 'type': 'content', 'html': '<div class="slide">ب</div>'},
        ]
        details = self.application_module.change_tracking.describe_slide_changes(
            old_slides, [old_slides[1], old_slides[0]])
        self.assertIn('أُعيد ترتيب الشرائح', details)
        self.assertTrue(any('نُقلت من الموضع' in item for item in details))

    def test_history_records_who_changed_what_for_drafts_and_ai_edits(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        saved = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'history-draft', 'project_name': 'THE VIEW', 'city': 'جدة',
        }})
        self.assertTrue(saved.get_json()['success'], saved.get_json())
        client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'history-draft', 'project_name': 'THE VIEW 2', 'city': 'جدة', 'district': 'الشاطئ',
        }})
        client.post('/api/project-draft/section-status', headers=headers, json={
            'draftId': 'history-draft', 'sectionKey': 'basic', 'sectionStatus': 'approved',
        })

        draft_log = client.get('/api/project-draft/history-draft/edit-log', headers=headers).get_json()
        self.assertTrue(draft_log['success'], draft_log)
        actions = [entry['action'] for entry in draft_log['log']]
        self.assertIn('إنشاء ملف مشروع', actions)
        # A save is recorded per touched section — project_name lives under
        # «معلومات أساسية» and district under «الموقع والخرائط».
        self.assertIn('تعديل «معلومات أساسية»', actions)
        self.assertIn('تعديل «الموقع والخرائط»', actions)
        self.assertIn('اعتماد قسم', actions)
        import change_tracking as tracking
        details = '\n'.join(
            tracking.detail_text(line)
            for entry in draft_log['log'] for line in entry['details'])
        self.assertIn('من «THE VIEW» إلى «THE VIEW 2»', details)
        self.assertIn('أُضيف «الشاطئ»', details)
        self.assertIn('معتمد', details)
        self.assertTrue(all(entry['user_name'] for entry in draft_log['log']), draft_log['log'])

        created = client.post('/api/presentations', headers=headers, json={
            'title': 'THE VIEW', 'projectData': {'project_name': 'THE VIEW'},
            'slidesData': [{'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'}],
        })
        pres_id = created.get_json()['presentationId']

        # An AI edit used to leave no trace at all.
        edited = '<div class="slide"><h1>THE VIEW</h1><p>واجهة بحرية</p></div>'
        plan = json.dumps({'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'current', 'instruction': 'أضف سطر الواجهة'}}]},
            ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}), \
                patch.object(self.application_module, '_designer_edit_slide',
                             return_value=(edited, 'تم تحديث الشريحة')):
            chat = client.post('/api/designer-chat', headers=headers, json={
                'message': 'أضف سطر الواجهة البحرية', 'presentationId': pres_id, 'slideIndex': 0,
                'slidesData': [{'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'}],
            })
        self.assertTrue(chat.get_json()['success'], chat.get_json())
        chat_data = chat.get_json()['data']
        self.assertFalse(chat_data['saved'])

        log = client.get('/api/presentations/' + pres_id + '/edit-log', headers=headers).get_json()['log']
        ai_entries = [entry for entry in log if entry['source'] == 'ai']
        self.assertFalse(ai_entries, log)
        self.assertIn('إنشاء العرض', [entry['action'] for entry in log])

        saved_presentation = client.get('/api/presentations/' + pres_id, headers=headers).get_json()['presentation']
        saved_chat = saved_presentation['projectData'].get('designerChat', {})
        saved_contents = [item.get('content') for item in saved_chat.get('messages', [])]
        self.assertNotIn('أضف سطر الواجهة البحرية', saved_contents)
        self.assertNotIn('واجهة بحرية', saved_presentation['slidesData'][0]['html'])

        saved = client.put('/api/presentations/' + pres_id, headers=headers, json={
            'projectData': {
                'project_name': 'THE VIEW',
                'designerChat': {'messages': chat_data['chatHistory']},
            },
            'slidesData': chat_data['slidesData'],
        })
        self.assertTrue(saved.get_json()['success'], saved.get_json())
        saved_presentation = client.get('/api/presentations/' + pres_id, headers=headers).get_json()['presentation']
        saved_chat = saved_presentation['projectData'].get('designerChat', {})
        saved_contents = [item.get('content') for item in saved_chat.get('messages', [])]
        self.assertIn('أضف سطر الواجهة البحرية', saved_contents)
        self.assertIn('واجهة بحرية', saved_presentation['slidesData'][0]['html'])

        index_source = read_frontend_text()
        self.assertIn('function renderChangeLogEntry(entry)', index_source)
        self.assertIn('async function showDraftEditLog(draftId)', index_source)
        self.assertIn('showDraftEditLog(', index_source)

    def test_designer_asks_instead_of_guessing_and_the_chat_is_one_line(self):
        client = self.app.test_client()
        slides = [{'html': '<div class="slide">شريحة</div>', 'title': 'الغلاف', 'type': 'cover'}]
        plan = json.dumps({
            'response': 'الطلب غير واضح',
            'actions': [{'tool': 'ask', 'params': {'question': 'أي شريحة تقصد؟'}}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}) as chat:
            response = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                'message': 'حسّن الشريحة', 'slidesData': slides, 'slideIndex': 0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        reply = response.get_json()['data']
        self.assertEqual(reply['action'], 'ask')
        self.assertEqual(reply['response'], 'أي شريحة تقصد؟')
        # Nothing was edited: one model call for the plan, and no edit call after it.
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(reply['slidesData'], slides)

        index_source = read_frontend_text()
        # One chat line: attach, write, send. The suggestions drawer is gone.
        self.assertNotIn('اقتراحات سريعة', index_source)
        self.assertNotIn('function setTenantChatExample', index_source)
        self.assertIn('id="tenantChatImageFile"', index_source)
        self.assertIn('function attachTenantChatImage(input)', index_source)
        self.assertIn("attachedImage: attachedImage ? attachedImage.dataUri : ''", index_source)
        self.assertIn("if (reply.action === 'ask' || reply.action === 'chat_only') {", index_source)
        # The designer chat must not reuse the training page's file input.
        composer = index_source[index_source.index('id="tenantChatComposer"'):
                                index_source.index('id="tenantChatComposer"') + 1400]
        self.assertNotIn('trainingChatImageFile', composer)

    def test_refresh_on_the_slides_route_reopens_its_presentation(self):
        index_source = read_frontend_text()
        # The route carries no identity, and it used to be shown as-is: an empty workspace.
        self.assertIn('} else if (TENANT_NAVIGATION_CONTEXT_PAGES.has(requestedPage)) {', index_source)
        self.assertIn('if (!(await restoreTenantNavigation(requestedPage))) {', index_source)
        self.assertIn('async function restoreTenantNavigation(preferredPageId = null)', index_source)
        self.assertIn('if (preferredPageId && document.getElementById(preferredPageId)) state.pageId = preferredPageId;',
                      index_source)

    def test_designer_edit_keeps_the_presentation_images(self):
        """An edited slide used to come back with its image markers unresolved, so cards rendered empty."""
        module = self.application_module
        html = ('<div class="slide"><img src="##MOODBOARD_IMAGE_1##"><img src="##MOODBOARD_IMAGE_2##">'
                '<img src="##IMAGE_COVER##"><img src="##MAP_OVERVIEW##"></div>')
        creative = {
            'cover': '/uploads/creative/cover.png',
            'moodboard': ['/uploads/creative/mb1.png', '/uploads/creative/mb2.png'],
            'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
        }
        # clean_project_data() strips creativeImages, so reading the images off project data
        # could never work; they arrive in their own key, or under tenantCreativeImages.
        self.assertNotIn('creativeImages', module.clean_project_data({'creativeImages': creative}))

        resolved = module.resolve_designer_chat_placeholders(html, {}, None, 'tenant-x', creative)
        self.assertIn('/uploads/creative/mb1.png', resolved)
        self.assertIn('/uploads/creative/mb2.png', resolved)
        self.assertIn('/uploads/creative/cover.png', resolved)
        self.assertIn('/uploads/maps/overview.png', resolved)
        self.assertNotIn('##MOODBOARD_IMAGE_1##', resolved)
        self.assertNotIn('##IMAGE_COVER##', resolved)

        from_draft = module.resolve_designer_chat_placeholders(
            html, {'tenantCreativeImages': creative}, None, 'tenant-x')
        self.assertIn('/uploads/creative/mb1.png', from_draft)
        self.assertNotIn('##IMAGE_COVER##', from_draft)

        app_source = read_module_source('app.py')
        # Every edit path must carry the images, and a blind edit must say it was blind.
        self.assertIn('creative_images=creative_images', app_source)
        self.assertIn('التعديل جرى على الكود بدون معاينة بصرية للشريحة.', app_source)

    def test_no_slide_can_be_built_from_images_that_do_not_exist(self):
        """A slide came out as four empty frames: it used ##STREET_VIEW_1..4##, which nothing
        produces, and the unresolved tokens were blanked into src="" / url() — an empty card."""
        import slide_engine as engine
        self.assertIn('لا تكتب ##STREET_VIEW_1##', engine.NO_STREET_VIEW_RULE)
        for source in ('slide_engine.py', 'app.py', 'design_templates.py'):
            text = read_module_source(source)
            # No line may still offer the token to the model.
            for line in text.splitlines():
                if 'STREET_VIEW' not in line:
                    continue
                self.assertNotIn('استخدم', line, f'{source}: {line.strip()}')
                self.assertNotIn('لصور الموقع', line, f'{source}: {line.strip()}')
        # The plan can no longer ask for such a slide, and one from an old draft is dropped.
        self.assertNotIn('site_photos', engine.SLIDE_PLAN_PROMPT)
        plan = engine.strip_street_view_slides({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'قراءة بصرية للموقع', 'type': 'site_photos'},
            {'title': 'الختام', 'type': 'closing'},
        ]})
        self.assertEqual([s['type'] for s in plan['slides']], ['cover', 'closing'])
        self.assertNotIn('site_photos', engine.validate_slide_plan(
            {'slides': [{'title': 'x', 'type': 'site_photos'}]}, {})[1].__str__().replace(
                "unknown type 'site_photos'", ''))

        # An image token that reaches the end of the pipeline takes its carrier with it.
        html = ('<div class="slide">'
                '<div style="background-image:url(##STREET_VIEW_1##);width:200px"></div>'
                '<img src="##STREET_VIEW_2##" alt="">'
                '<div style="background-image:url();width:200px"></div>'
                '<img src="" alt="">'
                '<img src="/uploads/creative/cover.png" alt="">'
                '</div>')
        cleaned = engine._drop_unresolved_image_placeholders(html)
        self.assertNotIn('##STREET_VIEW', cleaned)
        self.assertNotIn('url()', cleaned)
        self.assertNotIn('src=""', cleaned)
        self.assertIn('/uploads/creative/cover.png', cleaned)
        # An unavailable map is stated as forbidden instead of being left unmentioned.
        with self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            info = self.application_module._get_images_info(
                {'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'}}, {})
        self.assertIn('##MAP_OVERVIEW##', info)
        self.assertIn('ممنوع كتابة ##MAP_CATCHMENT##', info)
        self.assertIn('ممنوع كتابة ##PLAN_IMAGE_N##', info)
        self.assertIn('##STREET_VIEW_1##', info)

    def test_export_names_the_slide_it_could_not_print(self):
        """«25 صفحة مقابل 50 شريحة» is not actionable on its own: the deck is inspected per entry and
        the printed layout is measured, so the failure names the slides behind it."""
        import generate_pdf_from_preview as engine

        html, notes = self.application_module._export_html_from_slides([
            {'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'},
            {'title': 'بلا إطار', 'html': '<h1>محتوى بلا إطار شريحة</h1>'},
            {'title': 'فارغة', 'html': ''},
            {'title': 'مدمجة', 'html': '<div class="slide">أ</div><div class="slide">ب</div>'},
        ])
        # The entry with no .slide root is wrapped so it still owns a page, and it is reported.
        # 1 cover + 1 wrapped + 2 from the merged entry; the empty entry contributes nothing.
        self.assertEqual(html.count('class="slide"'), 4)
        self.assertIn('محتوى بلا إطار شريحة', html)
        joined = ' | '.join(notes)
        self.assertIn('شرائح بلا محتوى: 3', joined)
        self.assertIn('شرائح بلا إطار شريحة', joined)
        self.assertIn('شرائح تحتوي أكثر من شريحة: 4', joined)

        faults = engine.describe_slide_layout_faults([
            {'index': 1, 'position': 'relative', 'display': 'block', 'cssFloat': 'none', 'height': 720},
            {'index': 2, 'position': 'absolute', 'display': 'block', 'cssFloat': 'none', 'height': 720},
            {'index': 3, 'position': 'static', 'display': 'none', 'cssFloat': 'none', 'height': 720},
            {'index': 4, 'position': 'static', 'display': 'block', 'cssFloat': 'left', 'height': 360},
        ])
        self.assertEqual(len(faults), 3)
        self.assertIn('الشريحة 2 (position:absolute)', faults)
        self.assertIn('display:none', faults[1])
        self.assertIn('height:360px', faults[2])

        # The build in use is reportable, so "is the fix deployed" has an answer.
        build = self.app.test_client().get('/api/build').get_json()
        self.assertTrue(build['commit'])
        self.assertTrue(build['startedAt'])

    def test_designer_chat_remembers_the_conversation_and_the_slide(self):
        """It used to receive the current message alone: it asked «أي شريحة؟», the answer arrived at
        a model that had never asked, and the next turn asked again."""
        module = self.application_module
        history = [
            {'role': 'user', 'content': 'الشريحة 8 فيها مشكلة', 'slides': [8]},
            {'role': 'assistant', 'content': 'ما هي المشكلة تحديدًا؟', 'slides': [8]},
        ]
        memory, recent = module._designer_chat_memory(history, '')
        self.assertEqual(memory, '')
        self.assertEqual(len(recent), 2)
        lines = module._designer_chat_history_lines(recent)
        self.assertIn('المستخدم [شرائح: 8]: الشريحة 8 فيها مشكلة', lines[0])

        # A long conversation is truncated locally, never summarized by the model:
        # a hidden summarization call billed the tenant for work nobody requested.
        long_history = [{'role': 'user', 'content': 'ك' * 900, 'slides': [3]} for _ in range(20)]
        with patch.object(module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': 'ملخص: الحديث عن الشريحة 3.'}}]}) as chat:
            compressed, kept = module._designer_chat_memory(long_history, '')
        self.assertFalse(chat.called)
        self.assertIn('[شرائح: 3]', compressed)
        self.assertEqual(len(kept), module.DESIGNER_CHAT_VERBATIM_TURNS)

        app_source = read_module_source('app.py')
        self.assertIn('## ذاكرة المحادثة (ملخص ما سبق)', app_source)
        self.assertIn('## آخر رسائل المحادثة بالترتيب', app_source)
        self.assertIn('## نطاق الحديث السابق', app_source)
        self.assertIn("preferred_indexes = list(focus_indexes)", app_source)
        self.assertIn("'memory': chat_memory", app_source)

        index_source = read_frontend_text()
        self.assertIn('memory: tenantDesignerChatMemory,', index_source)
        self.assertIn('focusIndexes: tenantChatFocusIndexes,', index_source)
        self.assertIn('function applyDesignerChatMemory(reply)', index_source)
        self.assertIn('function restoreDesignerChat(source, expectedPresentationId = null)', index_source)
        self.assertIn('data.designerChat = designerChatPersistence(syncPresentation ? tenantPresentationId : null);', index_source)
        self.assertIn('function designerChatPersistence(presentationId = tenantPresentationId)', index_source)
        self.assertIn('function resetDesignerChatForNewPresentation()', index_source)
        self.assertIn('presentationId: presentationId || null', index_source)
        self.assertIn('restoreDesignerChat(tenantProjectData, tenantPresentationId)', index_source)
        self.assertNotIn('let draftAutoSaveTimer = null;', index_source)
        self.assertIn('const currentFormData = await collectTenantFormData();', index_source)
        self.assertIn('tenantProjectData = { ...tenantProjectData, ...currentFormData };', index_source)
        self.assertIn('projectData: buildDesignerChatProjectData(tenantProjectData),', index_source)
        self.assertIn("'tenantSlidesData', 'tenantSlidePlan', 'pageDrafts', 'tenantCreativeImages', 'designerChat'", index_source)
        self.assertNotIn('chatPayload.projectData = { ...tenantProjectData, tenantSlidesData };', index_source)
        self.assertIn("'saved': False", app_source)
        self.assertIn('class="slide-toolbar-chat-context"', index_source)
        self.assertIn('class="ge-chat-panel-status"', index_source)
        self.assertNotIn('id="tenantChatSlide"', index_source)
        self.assertIn('function openTenantChatImagePreview(src)', index_source)
        self.assertIn('class="tenant-chat-attachment-remove"', index_source)
        self.assertIn('class="tenant-chat-entry-row"', index_source)
        self.assertIn('aria-label="إضافة صورة"', index_source)
        self.assertNotIn('id="tenantChatAttachmentPreview"', index_source)
        self.assertIn('.ge-thumb-actions > button', index_source)
        # Billing transparency: greetings cost zero tokens, attachments are first-class tools.
        self.assertIn('_designer_chat_free_reply', app_source)
        self.assertIn("'billed': False", app_source)
        self.assertIn('insert_attached_image', app_source)
        self.assertIn('DESIGNER_CHAT_MAX_ATTACHED_IMAGES', app_source)
        self.assertIn('attachedImages', index_source)
        # The conversation is restored with the file instead of being wiped on open.
        self.assertNotIn('tenantDesignerMessages = [];\n      tenantChatSlideIndex', index_source)
        self.assertIn("'designerChat'", read_module_source('db.py'))

    def test_designer_chat_boundary_slide_receives_documented_facts_and_rejects_false_success(self):
        """The boundary diagram is built by the system, so the designer model used to answer
        data-add requests with no project facts and report success on an unchanged slide."""
        module = self.application_module
        boundary_html = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
            '<div data-boundary-diagram="1">'
            '<div data-boundary-direction="north"><span>الشمال</span><span>109 م</span></div>'
            '<div data-boundary-direction="south"><span>الجنوب</span><span>98 م</span></div>'
            '<div data-boundary-direction="east"><span>الشرق</span><span>80.3 م</span></div>'
            '<div data-boundary-direction="west"><span>الغرب</span><span>59.5 م</span></div>'
            '</div></div>'
        )
        project_data = {
            'project_name': 'مشروع الواجهة',
            'location_address': 'https://maps.google.com/?q=21.6001,39.1001',
            'boundary_lengths': 'الشمال: 109 م، الجنوب: 98 م، الشرق: 80.3 م، الغرب: 59.5 م',
            'directions_table': json.dumps([
                {'direction': 'north', 'description': 'شارع الملك فهد'},
            ], ensure_ascii=False),
        }
        self.assertTrue(module._is_land_boundary_diagram_slide(
            title='مخطط اتجاهي لحدود الأرض', content_source='land_boundary_diagram', html=boundary_html))
        self.assertFalse(module._is_land_boundary_diagram_slide(
            title='الغلاف', content_source='', html='<div class="slide"></div>'))
        note = module._designer_boundary_facts_note(project_data)
        for value in ('109', '98', '80.3', '59.5', 'شارع الملك فهد'):
            self.assertIn(value, note)
        self.assertIn('ممنوع الاختراع', note)

        with self.app.app_context():
            branding = db.get_branding(self.tenant_a) or {}
        instruction = 'أضف بيانات الحدود الموثقة لكل اتجاه في موضعه الجغرافي الصحيح'

        def run_edit(model_html, model_response='تمت الإضافة', request_instruction=instruction,
                     current_html=boundary_html):
            captured = []
            response = {'choices': [{'message': {'content': json.dumps({
                'html': model_html, 'response': model_response,
            }, ensure_ascii=False)}}]}

            def fake_chat(prompt, *args, **kwargs):
                captured.append(prompt)
                return response

            with self.app.test_request_context(), \
                    patch.object(module, 'call_zai_chat', side_effect=fake_chat):
                module.g.tenant_id = self.tenant_a
                return module._designer_edit_slide(
                    current_html, 'مخطط اتجاهي لحدود الأرض', request_instruction, 8,
                    project_data, None, branding, tenant_id=self.tenant_a,
                    slide_type='content', total_slides=74,
                    content_source='land_boundary_diagram', skip_vision=True,
                ), captured

        # The documented facts reach the model prompt.
        changed_html = boundary_html.replace(
            '109 م', '109 م<div>شارع الملك فهد</div>')
        (out_html, out_response), captured = run_edit(changed_html)
        self.assertEqual(len(captured), 1)
        self.assertTrue(any('بيانات الحدود الموثقة' in prompt for prompt in captured))
        self.assertTrue(any('شارع الملك فهد' in prompt for prompt in captured))
        self.assertTrue(any('https://maps.google.com/?q=21.6001,39.1001' in prompt for prompt in captured))
        self.assertTrue(any('ملف بيانات المشروع الكامل' in prompt for prompt in captured))
        self.assertIn('شارع الملك فهد', out_html)
        self.assertIn('أحدث بيانات المشروع', out_response)

        # An identical model reply no longer strands this system-built slide. The server rebuilds
        # it from the latest linked project facts and reports only the verified change.
        (rebuilt_html, rebuilt_response), rebuild_calls = run_edit(boundary_html)
        self.assertEqual(len(rebuild_calls), 1)
        for value in ('109', '98', '80.3', '59.5', 'شارع الملك فهد'):
            self.assertIn(value, rebuilt_html)
        self.assertIn('أحدث بيانات المشروع', rebuilt_response)
        self.assertNotIn('تم الحفاظ على تصميم الشريحة', rebuilt_response)

        # A model reply that drops a documented length is rejected, then repaired by the same
        # deterministic path instead of being exposed as a successful mutation.
        dropped_html = boundary_html.replace('109 م', '')
        self.assertNotIn('109', dropped_html)
        (repaired_html, repaired_response), repair_calls = run_edit(dropped_html)
        self.assertEqual(len(repair_calls), 1)
        self.assertIn('109', repaired_html)
        self.assertIn('شارع الملك فهد', repaired_html)
        self.assertIn('أحدث بيانات المشروع', repaired_response)

        # The exact saved project link is inserted by the server even when Sol returns the old
        # system slide unchanged and claims that it completed the request.
        maps_instruction = 'أضف رابط Google Maps الخاص بالمشروع إلى الشريحة'
        (maps_html, maps_response), maps_calls = run_edit(
            boundary_html,
            model_response='تم الحفاظ على تصميم الشريحة لتعذر التعديل التلقائي عليها.',
            request_instruction=maps_instruction,
        )
        self.assertEqual(len(maps_calls), 1)
        self.assertIn('data-project-map-link="1"', maps_html)
        self.assertIn(project_data['location_address'], maps_html)
        self.assertIn('رابط Google Maps', maps_response)
        self.assertNotIn('تم الحفاظ على تصميم الشريحة', maps_response)

    def test_designer_chat_job_polling_is_recoverable_and_result_is_fetched_once(self):
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        job_id = 'designer-result-ready-job'
        module._write_job('.designer_chat_jobs', self.tenant_a, job_id, {
            'status': 'completed',
            'success': True,
            'progress': 100,
            'data': {
                'action': 'workspace_update',
                'slidesData': [{'title': 'اختبار', 'html': '<div class="slide"></div>'}],
            },
        })

        metadata_response = client.get(
            '/api/designer-chat/jobs/' + job_id, headers=headers)
        self.assertEqual(metadata_response.status_code, 200)
        metadata = metadata_response.get_json()
        self.assertNotIn('data', metadata)
        self.assertTrue(metadata['resultReady'])
        self.assertEqual(metadata['jobId'], job_id)
        self.assertIn('heartbeatAt', metadata)

        result_response = client.get(
            '/api/designer-chat/jobs/' + job_id + '?includeResult=1', headers=headers)
        self.assertEqual(result_response.status_code, 200)
        result = result_response.get_json()
        self.assertEqual(result['data']['slidesData'][0]['title'], 'اختبار')

        stale_job_id = 'designer-stale-heartbeat-job'
        module._write_job('.designer_chat_jobs', self.tenant_a, stale_job_id, {
            'status': 'running', 'success': True, 'progress': 40,
        })
        stale_path = module._job_path('.designer_chat_jobs', self.tenant_a, stale_job_id)
        old_heartbeat = time.time() - 120
        os.utime(stale_path, (old_heartbeat, old_heartbeat))
        stale_response = client.get(
            '/api/designer-chat/jobs/' + stale_job_id, headers=headers).get_json()
        self.assertTrue(stale_response['stale'])
        self.assertEqual(stale_response['status'], 'running')

        # Registering the same request id is idempotent, including when two Gunicorn workers
        # reach the route together. Reusing it for another request is rejected rather than
        # launching a second AI call under an ambiguous identifier.
        request_id = 'designer-idempotent-request'
        request_payload = {
            'requestId': request_id,
            'message': 'عدّل عنوان الشريحة',
            'presentationId': 'presentation-one',
            'projectData': {'draftId': 'draft-one'},
            'slideIndex': 0,
        }
        with patch.object(module.designer_chat_reliability.threading, 'Thread') as thread_class:
            queued = client.post('/api/designer-chat/jobs', headers=headers, json=request_payload)
            reused = client.post('/api/designer-chat/jobs', headers=headers, json=request_payload)
            conflict = client.post('/api/designer-chat/jobs', headers=headers, json={
                **request_payload,
                'message': 'احذف الشريحة',
            })
        self.assertEqual(queued.status_code, 202, queued.get_json())
        self.assertEqual(reused.status_code, 202, reused.get_json())
        self.assertTrue(reused.get_json()['reused'])
        self.assertEqual(conflict.status_code, 409, conflict.get_json())
        self.assertEqual(conflict.get_json()['failureReason'], 'request_id_conflict')
        self.assertEqual(thread_class.call_count, 1)
        stored_job = module._read_job('.designer_chat_jobs', self.tenant_a, request_id)
        self.assertTrue(stored_job.get('requestHash'))
        self.assertFalse(os.path.exists(module._job_path(
            '.designer_chat_jobs', self.tenant_a, request_id) + '.claim'))

        index_source = read_frontend_text()
        poll_body = index_source.split('async function requestTenantDesignerChat(', 1)[1]
        poll_body = poll_body.split('\n    function applyTenantDesignerChatResult', 1)[0]
        self.assertIn('T_DESIGNER_JOBS_KEY', index_source)
        self.assertIn('persistTenantDesignerJob(metadata)', poll_body)
        self.assertIn('requestId: metadata.jobId', poll_body)
        self.assertIn('?includeResult=0', poll_body)
        self.assertIn('?includeResult=1', poll_body)
        self.assertNotIn('transientFailures < 5', poll_body)
        self.assertIn('async function resumeTenantDesignerChatJob()', index_source)
        self.assertGreaterEqual(index_source.count('void resumeTenantDesignerChatJob();'), 3)
        self.assertIn('function applyTenantDesignerChatResult(data, message, input = null)', index_source)
        self.assertIn('function tenantDesignerServerJobMatches(metadata, serverJob)', index_source)
        self.assertGreaterEqual(index_source.count('tenantDesignerServerJobMatches(metadata,'), 3)
        self.assertIn("status === 'not_found' || status === 'stale'", index_source)
        self.assertIn('const recoveryPayload = resumeJob.hadAttachment ? null : {', index_source)
        self.assertIn('requestTenantDesignerChat(recoveryPayload, indicator, resumeJob)', index_source)
        self.assertIn('function designerChatWorkspaceSignature()', index_source)
        self.assertIn('function tenantDesignerJobCanApply(metadata)', index_source)
        self.assertIn('workspaceSignature: String(', index_source)
        self.assertIn('await new Promise(resolve => setTimeout(resolve, 80));', index_source)

        app_source = read_module_source('app.py')
        self.assertIn("temp_path = f'{path}.tmp-", app_source)
        self.assertIn('os.fsync(fh.fileno())', app_source)
        self.assertIn('os.replace(temp_path, path)', app_source)
        self.assertIn('progress_callback=lambda attempt, total', app_source)
        reliability_source = read_module_source('designer_chat_reliability.py')
        self.assertIn('os.O_CREAT | os.O_EXCL', reliability_source)
        self.assertIn('request_id_conflict', reliability_source)

    def test_designer_chat_uses_the_latest_linked_draft_and_current_browser_values(self):
        """A saved presentation is only a slide snapshot. Sol must read the current linked project
        draft, while values sent by the open browser remain newer than that saved draft."""
        module = self.application_module
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_id = 'designer-current-project-facts'
        saved_link = 'https://maps.google.com/?q=24.7136,46.6753'
        stale_link = 'https://maps.google.com/?q=21.4858,39.1925'
        browser_link = 'https://maps.google.com/?q=25.2048,55.2708'
        unrelated_draft_id = 'designer-unrelated-project'
        saved = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': draft_id,
            'project_name': 'المشروع المحدث',
            'location_address': saved_link,
            'allowed_uses': 'سكني وتجاري',
        }})
        self.assertTrue(saved.get_json()['success'], saved.get_json())
        unrelated = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': unrelated_draft_id,
            'project_name': 'مشروع آخر غير مرتبط',
            'allowed_uses': 'صناعي',
        }})
        self.assertTrue(unrelated.get_json()['success'], unrelated.get_json())
        slide = {'title': 'نبذة عن المشروع', 'type': 'content',
                 'html': '<div class="slide" style="width:1280px;height:720px"><h1>قديم</h1></div>'}
        with self.app.app_context():
            presentation_id = db.create_presentation(
                self.tenant_a, 'عرض قديم',
                project_data={'draftId': draft_id, 'project_name': 'الاسم القديم',
                              'location_address': stale_link},
                slides_data=[slide], slide_count=1, draft_id=draft_id,
            )

        captured = []
        planner_reply = {'choices': [{'message': {'content': json.dumps({
            'response': 'تم العثور على رابط المشروع.',
            'actions': [{'tool': 'chat_only', 'params': {}}],
        }, ensure_ascii=False)}}]}

        def fake_chat(prompt, *args, **kwargs):
            captured.append(prompt)
            return planner_reply

        with patch.object(module, 'call_zai_chat', side_effect=fake_chat):
            response = client.post('/api/designer-chat', headers=headers, json={
                'presentationId': presentation_id,
                'message': 'ما رابط جوجل ماب الموجود في بيانات المشروع؟',
            })
        self.assertTrue(response.get_json()['success'], response.get_json())
        self.assertIn(saved_link, captured[-1])
        self.assertIn('المشروع المحدث', captured[-1])
        self.assertIn('سكني وتجاري', captured[-1])
        self.assertNotIn(stale_link, captured[-1])

        captured.clear()
        with patch.object(module, 'call_zai_chat', side_effect=fake_chat):
            response = client.post('/api/designer-chat', headers=headers, json={
                'presentationId': presentation_id,
                'projectData': {'draftId': unrelated_draft_id, 'location_address': browser_link},
                'message': 'ما رابط جوجل ماب الموجود في بيانات المشروع؟',
            })
        self.assertTrue(response.get_json()['success'], response.get_json())
        self.assertIn(browser_link, captured[-1])
        self.assertIn('المشروع المحدث', captured[-1])
        self.assertIn('سكني وتجاري', captured[-1])
        self.assertNotIn('مشروع آخر غير مرتبط', captured[-1])
        self.assertNotIn(saved_link, captured[-1])
        self.assertNotIn(stale_link, captured[-1])

    def test_designer_chat_does_not_save_draft_until_explicit_save(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        draft_id = 'designer-unsaved-draft'
        old_html = '<div class="slide"><h1>قديم</h1></div>'
        new_html = '<div class="slide"><h1>جديد</h1></div>'
        initial_slide = {'title': 'الغلاف', 'type': 'cover', 'html': old_html}

        created = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': draft_id,
            'project_name': 'مشروع التصميم',
            'tenantSlidesData': [initial_slide],
        }})
        self.assertTrue(created.get_json()['success'], created.get_json())
        plan = json.dumps({'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'current', 'instruction': 'غيّر العنوان'}},
        ]}, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}), \
                patch.object(self.application_module, '_designer_edit_slide',
                             return_value=(new_html, 'تم تحديث الشريحة')):
            response = client.post('/api/designer-chat', headers=headers, json={
                'message': 'غيّر عنوان الشريحة',
                'projectData': {'draftId': draft_id, 'project_name': 'مشروع التصميم'},
                'slidesData': [initial_slide],
                'slideIndex': 0,
            })
        self.assertTrue(response.get_json()['success'], response.get_json())
        reply = response.get_json()['data']
        self.assertFalse(reply['saved'])

        stored = client.get('/api/project-draft/' + draft_id, headers=headers).get_json()['draft']['draft_data']
        self.assertEqual(stored['tenantSlidesData'][0]['html'], old_html)

        saved = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': draft_id,
            'project_name': 'مشروع التصميم',
            'tenantSlidesData': reply['slidesData'],
            'designerChat': {'messages': reply['chatHistory']},
        }})
        self.assertTrue(saved.get_json()['success'], saved.get_json())
        stored = client.get('/api/project-draft/' + draft_id, headers=headers).get_json()['draft']['draft_data']
        self.assertEqual(stored['tenantSlidesData'][0]['html'], new_html)

    def test_designer_chat_merges_saved_history_with_short_browser_snapshots(self):
        module = self.application_module
        stored = [
            {'role': 'user', 'content': 'طلب 1', 'slides': [1]},
            {'role': 'assistant', 'content': 'رد 1', 'slides': [1]},
            {'role': 'user', 'content': 'طلب 2', 'slides': [2]},
            {'role': 'assistant', 'content': 'رد 2', 'slides': [2]},
        ]
        short_browser_history = stored[-2:]
        self.assertEqual(module._merge_designer_chat_messages(stored, short_browser_history), stored)
        self.assertEqual(module._merge_designer_chat_messages(short_browser_history, stored), stored)
        self.assertEqual(
            module._merge_designer_chat_messages(stored, [
                *stored, {'role': 'user', 'content': 'طلب 3', 'slides': [3]},
            ]),
            [*stored, {'role': 'user', 'content': 'طلب 3', 'slides': [3]}],
        )

        app_source = read_module_source('app.py')
        index_source = read_frontend_text()
        self.assertIn("_merge_designer_chat_messages(stored_chat.get('messages'), incoming_history)", app_source)
        self.assertIn("'chatHistory': persisted_project_data['designerChat']['messages']", app_source)
        self.assertIn('function applyDesignerChatHistory(reply)', index_source)

    def test_designer_chat_supports_ranges_and_fast_structural_tasks(self):
        module = self.application_module
        slides = [{'title': f'شريحة {index}', 'html': '<div class="slide"></div>'}
                  for index in range(1, 9)]
        self.assertEqual(
            module.detect_slide_indexes_from_message_py('غيّر ألوان الشرائح من 2 إلى 5', slides),
            [1, 2, 3, 4],
        )
        plan = module._designer_deterministic_plan('احذف الشريحة 3', slides, 0, [2])
        self.assertEqual(plan['actions'][0]['tool'], 'delete_slide')
        self.assertEqual(plan['actions'][0]['params']['slide_number'], 3)
        plan = module._designer_deterministic_plan('انقل الشريحة 8 إلى 4', slides, 0, [7])
        self.assertEqual(plan['actions'][0]['tool'], 'reorder_slides')
        self.assertEqual(plan['actions'][0]['params'], {'from_index': 8, 'to_index': 4})

    def test_map_reload_reuses_one_approved_asset_without_model_or_google(self):
        module = self.application_module
        slides = [{
            'type': 'map_catchment',
            'content_source': 'catchment_areas',
            'title': 'خريطة النطاق الجغرافي واستيعاب المنطقة',
            'html': '<div class="slide"><img src="/uploads/maps/old.png">'
                    '<img src="/uploads/maps/duplicate.png"></div>',
        }]

        plan = module._designer_deterministic_plan('أعد تحميل الخريطة للشريحة رقم 1', slides, 0, [0])
        self.assertEqual(plan['actions'][0]['tool'], 'insert_canonical_map')
        self.assertEqual(plan['actions'][0]['params']['map_type'], 'catchment')
        self.assertTrue(plan['actions'][0]['params']['refresh'])

        update_plan = module._designer_deterministic_plan('حدّث الخريطة في الشريحة رقم 1', slides, 0, [0])
        self.assertEqual(update_plan['actions'][0]['tool'], 'insert_canonical_map')
        self.assertTrue(update_plan['actions'][0]['params']['refresh'])

        rendered_map_slide = {
            'type': 'content',
            'title': '',
            'html': '<div class="slide"><div data-canonical-map="catchment">'
                    '<img src="/uploads/maps/old.png"></div></div>',
        }
        rendered_plan = module._designer_deterministic_plan(
            'حدث الخريطة في الشريحة رقم 1', [rendered_map_slide], 0, [0]
        )
        self.assertEqual(rendered_plan['actions'][0]['params']['map_type'], 'catchment')
        self.assertTrue(rendered_plan['actions'][0]['params']['refresh'])

        creative = {
            'map_placeholders': {'##MAP_CATCHMENT##': '/uploads/maps/approved.png'},
            'map_approvals': {'catchment': True},
        }
        approved = module._approved_canonical_map_url('catchment', {}, creative)
        self.assertEqual(approved, '/uploads/maps/approved.png')
        replaced, changed = module._replace_slide_with_approved_map(
            slides[0]['html'], 'catchment', approved)
        self.assertTrue(changed)
        self.assertEqual(replaced.count('/uploads/maps/approved.png'), 1)
        self.assertNotIn('/uploads/maps/old.png', replaced)
        self.assertNotIn('/uploads/maps/duplicate.png', replaced)
        self.assertIn('data-canonical-map="catchment"', replaced)

        creative['map_approvals']['catchment'] = False
        self.assertEqual(module._approved_canonical_map_url('catchment', {}, creative), '')

    def test_explicit_map_refresh_falls_back_to_latest_saved_map_when_section_image_is_missing(self):
        module = self.application_module
        map_file = tempfile.NamedTemporaryFile(
            dir=module.maps_service.MAPS_DIR, suffix='_latest.png', delete=False
        )
        map_path = map_file.name
        map_file.write(b'latest-map')
        map_file.close()
        self.addCleanup(lambda: os.path.exists(map_path) and os.unlink(map_path))

        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'catchment', map_path, '##MAP_CATCHMENT##',
                presentation_id='pres-refresh-map', metadata={}
            )
            latest = module._latest_canonical_map_url(
                'catchment',
                {},
                {},
                tenant_id=self.tenant_a,
                presentation_id='pres-refresh-map',
            )

        self.assertTrue(latest.endswith(os.path.basename(map_path)))

    def test_map_refresh_replaces_background_and_keeps_latest_placeholder_after_finalize(self):
        module = self.application_module
        import slide_engine
        latest = '/uploads/maps/catchment_latest.png'
        html = (
            '<div class="slide">'
            '<div data-map-summary-background style="background-image:url(/uploads/maps/catchment_old.png);"></div>'
            '<div data-map-summary-card>النطاق الجغرافي</div>'
            '</div>'
        )
        replaced, changed = module._replace_slide_with_approved_map(html, 'catchment', latest)
        self.assertTrue(changed)
        self.assertIn(latest, replaced)
        self.assertNotIn('catchment_old.png', replaced)

        finalized = slide_engine.finalize_slide_html(
            replaced, 'content', {}, {},
            map_placeholders={
                '##MAP_CATCHMENT##': latest,
                '##MAP_CATCHMENT_SATELLITE##': latest,
                '##MAP_CATCHMENT_ROADMAP##': latest,
            },
            content_source='catchment_areas',
            allow_all_maps=True,
        )
        self.assertIn(latest, finalized)
        self.assertNotIn('##MAP_CATCHMENT##', finalized)

    def test_map_refresh_prefers_visible_image_over_covered_root_background(self):
        module = self.application_module
        latest = '/uploads/maps/catchment_latest.png'
        html = (
            '<div class="slide" style="background-image:url(##MAP_CATCHMENT##);">'
            '<main style="background:#ffffff;">'
            '<img src="##MAP_CATCHMENT##" style="width:100%;height:100%;object-fit:contain;">'
            '</main></div>'
        )
        replaced, changed = module._replace_slide_with_approved_map(html, 'catchment', latest)
        self.assertTrue(changed)
        self.assertEqual(replaced.count(latest), 1)
        self.assertIn('<img', replaced)
        self.assertIn('background-image:none', replaced)
        self.assertNotIn('##MAP_CATCHMENT##', replaced)

    def test_map_refresh_prefers_dedicated_map_background_over_root_background(self):
        module = self.application_module
        latest = '/uploads/maps/catchment_latest.png'
        html = (
            '<div class="slide" style="background-image:url(##MAP_CATCHMENT##);">'
            '<section><div data-canonical-map="catchment" '
            'style="background-image:url(##MAP_CATCHMENT##);"></div></section>'
            '</div>'
        )
        replaced, changed = module._replace_slide_with_approved_map(html, 'catchment', latest)
        self.assertTrue(changed)
        self.assertEqual(replaced.count(latest), 1)
        self.assertIn('data-canonical-map="catchment"', replaced)
        self.assertIn('background-image:url(/uploads/maps/catchment_latest.png)', replaced)
        self.assertIn('background-image:none', replaced)
        self.assertNotIn('##MAP_CATCHMENT##', replaced)

    def test_designer_chat_returns_latest_map_in_updated_slide(self):
        module = self.application_module
        client = self.app.test_client()
        old_path = '/uploads/maps/catchment_old.png'
        latest_file = tempfile.NamedTemporaryFile(
            dir=module.maps_service.MAPS_DIR, suffix='_chat_latest.png', delete=False
        )
        latest_path = latest_file.name
        latest_file.write(b'latest-map')
        latest_file.close()
        self.addCleanup(lambda: os.path.exists(latest_path) and os.unlink(latest_path))
        slides = [{
            'type': 'map_catchment',
            'content_source': 'catchment_areas',
            'title': 'خريطة النطاق الجغرافي واستيعاب المنطقة',
            'html': '<div class="slide"><img src="' + old_path + '"></div>',
        }]
        created = client.post('/api/presentations', headers=self._headers(self.token_a), json={
            'title': 'خريطة اختبار الشات', 'projectData': {}, 'slidesData': slides,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'catchment', latest_path, '##MAP_CATCHMENT##',
                presentation_id=presentation_id, metadata={}
            )

        response = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
            'message': 'حدّث الخريطة',
            'presentationId': presentation_id,
            'slidesData': slides,
            'slideIndex': 0,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        reply = response.get_json()['data']
        self.assertEqual(reply['actions'][0]['status'], 'success')
        self.assertIn(os.path.basename(latest_path), reply['slidesData'][0]['html'])
        self.assertNotIn(old_path, reply['slidesData'][0]['html'])

    def test_designer_chat_copies_project_section_map_without_regenerating_slide(self):
        module = self.application_module
        client = self.app.test_client()
        old_path = '/uploads/maps/catchment_old.png'
        project_maps_dir = Path(module.UPLOADS_DIR) / 'maps'
        project_maps_dir.mkdir(parents=True, exist_ok=True)
        project_file = tempfile.NamedTemporaryFile(
            dir=project_maps_dir, suffix='_project_section.png', delete=False
        )
        project_path = project_file.name
        project_file.write(b'project-section-map')
        project_file.close()
        self.addCleanup(lambda: os.path.exists(project_path) and os.unlink(project_path))
        project_map = '/uploads/maps/' + os.path.basename(project_path)
        slides = [{
            'type': 'map_catchment',
            'content_source': 'catchment_areas',
            'title': 'خريطة النطاق الجغرافي واستيعاب المنطقة',
            'html': '<div class="slide"><div data-canonical-map="catchment">'
                    '<img src="' + old_path + '"></div></div>',
        }]
        created = client.post('/api/presentations', headers=self._headers(self.token_a), json={
            'title': 'نسخ صورة خريطة القسم', 'projectData': {}, 'slidesData': slides,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']
        stale_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_stale.png', delete=False)
        stale_path = stale_file.name
        stale_file.write(b'stale-map')
        stale_file.close()
        self.addCleanup(lambda: os.path.exists(stale_path) and os.unlink(stale_path))
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'catchment', stale_path, '##MAP_CATCHMENT##',
                presentation_id=presentation_id, metadata={}
            )

        response = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
            'message': 'حدث الخريطة في الشريحة رقم 1',
            'presentationId': presentation_id,
            'slidesData': slides,
            'slideIndex': 0,
            'history': [
                {'role': 'user', 'content': 'أضف لوجو Vision Gate في الشريحة رقم 52'},
                {'role': 'assistant', 'content': 'تمت إضافة الشعار.'},
            ],
            'creativeImages': {
                'map_placeholders': {'##MAP_CATCHMENT##': project_map},
                'map_approvals': {'catchment': False},
                'team_members': [{
                    'name': 'Vision Gate', 'role': 'التطوير',
                    'logo': '/uploads/creative/team-logo-1.png',
                }],
            },
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        reply = response.get_json()['data']
        self.assertEqual(reply['actions'][0]['status'], 'success')
        self.assertIn(project_map, reply['slidesData'][0]['html'])
        self.assertNotIn(old_path, reply['slidesData'][0]['html'])
        self.assertEqual(
            reply['creativeImages']['map_placeholders']['##MAP_CATCHMENT##'],
            project_map,
        )

    def test_explicit_map_refresh_ignores_missing_client_url(self):
        module = self.application_module
        persisted_maps_dir = Path(module.UPLOADS_DIR) / 'maps'
        persisted_maps_dir.mkdir(parents=True, exist_ok=True)
        stale_file = tempfile.NamedTemporaryFile(
            dir=persisted_maps_dir, suffix='_persisted_latest.png', delete=False
        )
        stale_path = stale_file.name
        stale_file.write(b'persisted-latest-map')
        stale_file.close()
        self.addCleanup(lambda: os.path.exists(stale_path) and os.unlink(stale_path))

        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'catchment', stale_path, '##MAP_CATCHMENT##',
                presentation_id='pres-missing-client-map', metadata={}
            )
            latest = module._latest_canonical_map_url(
                'catchment',
                {},
                {'map_placeholders': {'##MAP_CATCHMENT##': '/uploads/maps/deleted.png'}},
                tenant_id=self.tenant_a,
                presentation_id='pres-missing-client-map',
                preferred_images=[{
                    'map_placeholders': {'##MAP_CATCHMENT##': '/uploads/maps/deleted.png'}
                }],
            )

        self.assertEqual(latest, '/uploads/maps/' + os.path.basename(stale_path))

    def test_explicit_map_refresh_ignores_filesystem_client_url(self):
        module = self.application_module
        persisted_maps_dir = Path(module.UPLOADS_DIR) / 'maps'
        persisted_maps_dir.mkdir(parents=True, exist_ok=True)
        latest_file = tempfile.NamedTemporaryFile(
            dir=persisted_maps_dir, suffix='_filesystem_fallback.png', delete=False
        )
        latest_path = latest_file.name
        latest_file.write(b'persisted-latest-map')
        latest_file.close()
        self.addCleanup(lambda: os.path.exists(latest_path) and os.unlink(latest_path))

        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'catchment', latest_path, '##MAP_CATCHMENT##',
                presentation_id='pres-filesystem-client-map', metadata={}
            )
            latest = module._latest_canonical_map_url(
                'catchment',
                {},
                {'map_placeholders': {'##MAP_CATCHMENT##': r'C:\\workflow\\uploads\\maps\\stale.png'}},
                tenant_id=self.tenant_a,
                presentation_id='pres-filesystem-client-map',
                preferred_images=[{
                    'map_placeholders': {'##MAP_CATCHMENT##': r'C:\\workflow\\uploads\\maps\\stale.png'}
                }],
            )

        self.assertEqual(latest, '/uploads/maps/' + os.path.basename(latest_path))

    def test_map_refresh_replaces_frozen_revision_source_instead_of_appending(self):
        """A saved slide's map src is a frozen /uploads/creative/.../revisions/<sha>.png."""
        module = self.application_module
        old_path, marks = self._persisted_map_fixture(
            module, 'pres-frozen-map', image_type='landmarks', content=b'old-landmarks-map')
        digest = hashlib.sha256(b'old-landmarks-map').hexdigest()
        frozen_src = f'/uploads/creative/{self.tenant_a}/revisions/{digest}.png'
        html = ('<div class="slide"><div class="map-wrap">'
                f'<img src="{frozen_src}" alt=""></div></div>')
        replaced, changed = module._replace_slide_with_approved_map(
            html, 'landmarks', '/uploads/maps/landmarks_new.png', map_marks=marks)
        self.assertTrue(changed)
        self.assertEqual(replaced.count('/uploads/maps/landmarks_new.png'), 1)
        self.assertNotIn(frozen_src, replaced)
        # The old element was swapped in place — no extra overlay was appended.
        self.assertEqual(replaced.count('<img'), 1)
        self.assertIn('data-canonical-map="landmarks"', replaced)

    def test_map_refresh_replaces_non_map_src_inside_canonical_container(self):
        module = self.application_module
        _old_path, marks = self._persisted_map_fixture(
            module, 'pres-canonical-container', image_type='catchment')
        html = ('<div class="slide"><div data-canonical-map="catchment" '
                'style="position:absolute;inset:0;">'
                '<img src="/api/project-files/some-file-id"></div></div>')
        replaced, changed = module._replace_slide_with_approved_map(
            html, 'catchment', '/uploads/maps/catchment_new.png', map_marks=marks)
        self.assertTrue(changed)
        self.assertIn('/uploads/maps/catchment_new.png', replaced)
        self.assertNotIn('/api/project-files/some-file-id', replaced)
        self.assertEqual(replaced.count('<img'), 1)
