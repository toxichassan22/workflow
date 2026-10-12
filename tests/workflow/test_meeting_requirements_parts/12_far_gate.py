class MeetingRequirementsTestsPart12(MeetingRequirementsTests):

    def test_plans_distribution_prefers_client_approved_far_and_floors(self):
        """The client-entered approved FAR and floor count are the project's
        certified numbers — a distinguished parcel whose documented table is
        lower must not draw a false «معامل البناء» or floor-cap finding while
        the plan stays inside the approved figures, and documented values only
        apply when no approved value exists."""
        module = self.application_module
        rows = [{'id': 'r1', 'building': 'A', 'floor_range': '1-12',
                 'component': 'شقق', 'units_per_floor': 8, 'floor_area_sqm': 500}]
        context = {'land_area': 7000, 'components': [],
                   'floor_area_ratio': '7', 'approved_floor_count': '12'}
        regulations = {'floor_area_ratio': '6', 'table_floors': 10}
        checks = module._visual_concept_plan_distribution_checks(rows, [], context, regulations)
        self.assertFalse(any(c['item'] == 'تجاوز سقف الأدوار الموثق' for c in checks))
        self.assertFalse(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء' for c in checks))
        # Past the approved numbers the documented values must not rescue it.
        blocked = module._visual_concept_plan_distribution_checks(
            [dict(rows[0], floor_range='1-13', floor_area_sqm=3900)], [], context, regulations)
        self.assertTrue(any(c['item'] == 'تجاوز سقف الأدوار الموثق' for c in blocked))
        self.assertTrue(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء' for c in blocked))
        # Without approved values the documented table still governs.
        fallback = module._visual_concept_plan_distribution_checks(
            rows, [], {'land_area': 7000, 'components': []}, regulations)
        self.assertTrue(any(c['item'] == 'تجاوز سقف الأدوار الموثق' for c in fallback))
        self.assertFalse(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء' for c in fallback))

    def test_approved_floor_area_ratio_is_client_entered_and_ai_stripped(self):
        """The new land/croquis field rides the same guard rails as the other
        approved_* fields: it is a required client-only prebuilt field, the AI
        normalization paths strip it, and the visual-concept gate requires it."""
        fields = self.app.test_client().get(
            '/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        field = next(item for item in fields if item['fieldKey'] == 'approved_floor_area_ratio')
        self.assertEqual(field['fieldLabel'], 'معامل مسطح البناء المعتمد (FAR)')
        self.assertEqual(field['fieldType'], 'number')
        self.assertTrue(field['isRequired'])
        self.assertEqual(field['sectionKey'], 'land_croquis')
        module = self.application_module
        parcel = {'parcel_id': 'P-1', 'approved_floor_area_ratio': 7,
                  'floor_area_ratio': '6', 'table_floors': 10}
        module._normalize_parcel_scalar_fields(parcel)
        self.assertNotIn('approved_floor_area_ratio', parcel)
        result = module._normalize_land_document_result(
            {'approved_floor_area_ratio': 7,
             'parcels': [{'parcel_id': 'P-1', 'floor_area_ratio': '6'}]},
            project_type='سكني')
        self.assertNotIn('approved_floor_area_ratio', result)
        self.assertNotIn('approved_floor_area_ratio', result['parcels'][0])
        facts = module._visual_concept_facts({'approved_floor_area_ratio': ''})
        missing_keys = {item['key'] for item in module._visual_concept_missing_fields(facts)}
        self.assertIn('approved_floor_area_ratio', missing_keys)
        facts = module._visual_concept_facts({'approved_floor_area_ratio': 6.5})
        self.assertEqual(facts['approved_floor_area_ratio'], '6.5')
        missing_keys = {item['key'] for item in module._visual_concept_missing_fields(facts)}
        self.assertNotIn('approved_floor_area_ratio', missing_keys)

    def test_plans_distribution_prompt_carries_project_idea(self):
        """The recorded idea («3 مجمعات») is what tells the planner how many
        buildings to spread the program across — it must reach the distribution
        prompt even when the workflow hands back a planContext cached before the
        idea joined it, and the system prompt must tell the model to honour the
        recorded building count instead of collapsing into one mass."""
        module = self.application_module
        client = self.app.test_client()
        points = [
            {'point': 'P1', 'eastings': 1, 'northings': 1},
            {'point': 'P2', 'eastings': 2, 'northings': 1},
            {'point': 'P3', 'eastings': 2, 'northings': 2},
        ]
        idea = 'المشروع عبارة عن 3 مجمعات سكنية متوسطة الارتفاع'
        project_data = {
            'project_name': 'The View',
            'project_idea': idea,
            'project_components_data': [
                {'name': 'شقق', 'useType': 'residential', 'units': 12, 'builtArea': 1800},
            ],
        }
        cached_context = module._visual_concept_plan_context({'project_name': 'The View'}, [])
        cached_context.pop('project_idea', None)
        workflow = {'verification': {'approved': True},
                    'boundary': {'approved': True, 'points': points},
                    'planContext': cached_context}
        captured = {}

        def fake_chat(system_prompt, user_prompt, **kwargs):
            captured['system'] = system_prompt
            captured['user'] = user_prompt
            return {'choices': [{'message': {'content': '{"rows": []}'}}]}

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_chat):
            response = client.post('/api/visual-concept/plans-distribution',
                                   headers=self._headers(self.token_a),
                                   json={'projectData': project_data,
                                         'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('3 مجمعات', captured['user'])
        self.assertIn('مجمع', captured['system'])
        self.assertEqual(response.get_json()['planContext']['project_idea'], idea)

    def test_cached_plan_context_refreshes_live_far_and_land_values(self):
        """A planContext cached at verify time must not keep judging edits made
        since: the refresh re-reads the volatile land fields — approved FAR,
        coverage, land area, floors — from the live payload on every request, so
        a client who raises a distinguished parcel's FAR to 7 is no longer
        judged against the 6 the cache was built with."""
        module = self.application_module
        stale = module._visual_concept_plan_context(
            {'approved_floor_area_ratio': '6', 'croquis_land_area': '24912.95'})
        live = {'approved_floor_area_ratio': '7', 'croquis_land_area': '24912.95',
                'project_components_data': [
                    {'name': 'شقق', 'useType': 'residential', 'units': 12, 'builtArea': 1800}]}
        data = {'projectData': live,
                'plansWorkflow': {'boundary': {'approved': True, 'points': [
                    {'point': 'P1', 'eastings': 1, 'northings': 1},
                    {'point': 'P2', 'eastings': 2, 'northings': 1},
                    {'point': 'P3', 'eastings': 2, 'northings': 2}]},
                                  'planContext': stale}}
        _project, _workflow, _boundary, _points, context = \
            module._visual_concept_plans_context_from_request(data)
        self.assertEqual(context['floor_area_ratio'], '7')
        self.assertEqual(context['land_area'], '24912.95')
        self.assertTrue(context['components'])
        # The deterministic check judges the refreshed FAR: inside 7 but outside
        # the stale 6 must draw no «معامل البناء» finding.
        rows = [{'id': 'r1', 'building': 'A', 'floor_range': '1-8',
                 'component': 'شقق', 'floor_area_sqm': 20000}]
        checks = module._visual_concept_plan_distribution_checks(
            rows, [], context, context.get('regulations') or {})
        self.assertFalse(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء'
                             for c in checks))

    def test_open_use_rows_do_not_inflate_the_far_total(self):
        """ممشى ومساحات خضراء on «أرضي» are land program, not built floor area —
        a green buffer row must not push a plan that fits the approved FAR over
        the cap, while a covered use of the same size still trips it."""
        module = self.application_module
        self.assertEqual(
            module._visual_concept_plan_use_category(
                {'name': 'ممشى ومساحات خضراء'})[1], 'landscape')
        context = {'land_area': 24912.95, 'floor_area_ratio': '7', 'components': []}
        built = {'id': 'r1', 'building': 'A', 'floor_range': '1-8',
                 'component': 'شقق', 'floor_area_sqm': 21000}
        green = {'id': 'r2', 'building': '', 'floor_range': 'أرضي',
                 'component': 'ممشى ومساحات خضراء', 'floor_area_sqm': 11000}
        checks = module._visual_concept_plan_distribution_checks(
            [built, green], [], context, {})
        self.assertFalse(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء'
                             for c in checks))
        covered = dict(green, component='قاعة احتفالات')
        checks = module._visual_concept_plan_distribution_checks(
            [built, covered], [], context, {})
        self.assertTrue(any(c['item'] == 'إجمالي المسطحات يتجاوز معامل البناء'
                            for c in checks))

    def test_proposal_backfills_units_and_areas_from_the_recorded_program(self):
        """A model proposal that ships blank units/area cells gets them filled
        from the recorded program — the component's required units and area
        spread evenly across the floors its rows span — so the suggestion
        already satisfies the study instead of surfacing deltas for the client
        to fix by hand. Filled rows keep their values; the missing ones take
        the remainder."""
        module = self.application_module
        context = {'land_area': 10000, 'floor_area_ratio': '7',
                   'components': [
                       {'name': 'شقق سكنية', 'units': 80, 'builtArea': 9600},
                       {'name': 'المعارض التجارية', 'builtArea': 2100}]}
        raw = {'rows': [
            {'building': 'أ', 'floor_range': '1-8', 'component': 'شقق سكنية'},
            {'building': 'أ', 'floor_range': 'أرضي', 'component': 'المعارض التجارية'},
            {'building': 'ب', 'floor_range': 'أرضي', 'component': 'المعارض التجارية'}]}
        rows = module._visual_concept_plan_normalize_distribution(
            raw, context, {}, backfill=True)['rows']
        self.assertEqual(rows[0]['units_per_floor'], 10)
        self.assertEqual(rows[0]['floor_area_sqm'], 1200)
        self.assertEqual(rows[1]['floor_area_sqm'], 1050)
        self.assertEqual(rows[2]['floor_area_sqm'], 1050)
        filled = {'rows': [
            {'building': 'أ', 'floor_range': '1-4', 'component': 'شقق سكنية',
             'units_per_floor': 15, 'floor_area_sqm': 1000},
            {'building': 'ب', 'floor_range': '1-4', 'component': 'شقق سكنية'}]}
        remainder = module._visual_concept_plan_normalize_distribution(
            filled, context, {}, backfill=True)['rows'][1]
        self.assertEqual(remainder['units_per_floor'], 5)
        self.assertEqual(remainder['floor_area_sqm'], 1400)
        # The check path never refills: a cell the client cleared stays empty.
        cleared = module._visual_concept_plan_normalize_distribution(
            raw, context, {})['rows']
        self.assertIsNone(cleared[0]['units_per_floor'])
