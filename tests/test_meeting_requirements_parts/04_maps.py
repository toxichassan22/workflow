class MeetingRequirementsTestsPart03(MeetingRequirementsTests):

    def test_local_generated_image_reference_is_embedded_for_moodboard_generation(self):
        """Generated cover URLs must be converted before the vision request uses them."""
        response = Mock(status_code=200)
        response.json.return_value = {
            'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,result'}}]}}]
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module.requests, 'post', return_value=response) as request_post, \
                patch.object(self.application_module.os.path, 'isfile', return_value=True), \
                patch.object(self.application_module.os.path, 'getsize', return_value=3), \
                patch('builtins.open', mock_open(read_data=b'abc')):
            result = self.application_module.call_image_api_with_reference(
                '/uploads/creative/tenant-a/cover.png?t=1', 'moodboard prompt',
                usage_ctx={'tenant_id': 'tenant-a'}
            )

        self.assertEqual(result, 'data:image/png;base64,result')
        request_payload = request_post.call_args.kwargs['json']
        reference_url = request_payload['input_references'][0]['image_url']['url']
        self.assertEqual(reference_url, 'data:image/png;base64,YWJj')

    def test_visual_concept_image_response_accepts_content_image_parts(self):
        module = self.application_module
        response = Mock(status_code=200)
        response.json.return_value = {
            'choices': [{'message': {'content': [
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,from-content'}}
            ]}}]
        }
        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module.requests, 'post', return_value=response):
            result = module.call_image_api_with_references(
                'prompt', ['data:image/png;base64,AAAA', 'data:image/png;base64,BBBB']
            )
        self.assertEqual(result, 'data:image/png;base64,from-content')

    def test_visual_concept_keeps_five_reference_file_ids(self):
        module = self.application_module
        ids = [f'file-{index}' for index in range(7)]
        result = module._visual_concept_style_reference_ids({
            'visual_concept': {'styleReferenceFileIds': ids}
        })
        self.assertEqual(result, ids[:5])

    def test_osm_boundary_ignores_landuse_and_selects_containing_building(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'elements': [
                {
                    'type': 'way',
                    'tags': {'landuse': 'industrial'},
                    'geometry': [
                        {'lat': 24.0, 'lon': 46.0},
                        {'lat': 24.0, 'lon': 46.01},
                        {'lat': 24.01, 'lon': 46.01},
                        {'lat': 24.01, 'lon': 46.0},
                    ],
                },
                {
                    'type': 'way',
                    'tags': {'building': 'commercial'},
                    'geometry': [
                        {'lat': 23.9998, 'lon': 45.9998},
                        {'lat': 23.9998, 'lon': 46.0002},
                        {'lat': 24.0002, 'lon': 46.0002},
                        {'lat': 24.0002, 'lon': 45.9998},
                    ],
                },
            ]
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            coords = self.application_module.maps_service._fetch_osm_polygon(24.0, 46.0)

        self.assertEqual(len(coords), 4)
        self.assertLess(self.application_module.maps_service._approx_polygon_area_sqm(coords), 100000)

    def test_osm_boundary_returns_none_without_building_footprint(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'elements': [{
                'type': 'way',
                'tags': {'landuse': 'commercial'},
                'geometry': [
                    {'lat': 24.0, 'lon': 46.0},
                    {'lat': 24.0, 'lon': 46.01},
                    {'lat': 24.01, 'lon': 46.01},
                ],
            }]
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            coords = self.application_module.maps_service._fetch_osm_polygon(24.0, 46.0)

        self.assertIsNone(coords)

    def test_site_analysis_can_defer_map_generation(self):
        client = self.app.test_client()
        fields = {'location_lat': 25.1, 'location_lng': 47.6, 'nearby_landmarks': 'معلم'}
        with patch.object(self.application_module.maps_service, 'extract_coords_from_maps_link', return_value={'lat': 25.1, 'lng': 47.6}), \
                patch.object(self.application_module, '_collect_site_fields', return_value=(fields, [], [], [], [], [], None, {})), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {'location_address': 'https://www.google.com/maps/@25.1,47.6,17z'},
                'generateMaps': False,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['mapsDeferred'])
        generate_maps.assert_not_called()

    def test_site_analysis_rejects_legacy_map_generation_before_analysis_calls(self):
        client = self.app.test_client()
        with patch.object(self.application_module, '_collect_site_fields') as collect_fields, \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {'location_address': 'https://www.google.com/maps/@25.1,47.6,17z'},
                'generateMaps': True,
            })

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'INDIVIDUAL_MAP_GENERATION_REQUIRED')
        collect_fields.assert_not_called()
        generate_maps.assert_not_called()

    def test_land_document_form_uses_one_multi_file_field(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        keys = {field['fieldKey'] for field in fields}
        self.assertIn('land_documents_files', keys)
        self.assertNotIn('land_image_file', keys)
        self.assertNotIn('regulation_reference_file', keys)
        self.assertNotIn('croquis_file', keys)
        self.assertNotIn('building_permit_file', keys)
        self.assertNotIn('north_direction', keys)

    def test_approved_floor_count_is_client_entered_and_distinct_from_allowed_floors(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        field = next(item for item in fields if item['fieldKey'] == 'approved_floor_count')
        self.assertEqual(field['fieldLabel'], 'الأدوار المعتمدة')
        self.assertEqual(field['fieldType'], 'number')
        self.assertTrue(field['isRequired'])
        coverage = next(item for item in fields if item['fieldKey'] == 'approved_coverage_ratio')
        self.assertEqual(coverage['fieldLabel'], 'التغطية المعتمدة (%)')
        self.assertEqual(coverage['fieldType'], 'number')
        self.assertTrue(coverage['isRequired'])
        land_fields = {item['fieldKey']: item for item in fields}
        for key in ('building_ratio_coverage', 'setbacks', 'allowed_uses', 'regulatory_constraints', 'land_and_building_summary'):
            self.assertTrue(land_fields[key]['isRequired'])

        result = self.application_module._normalize_land_document_result({
            'parcels': [{'parcel_id': 'P-1', 'approved_floor_count': 7, 'max_floors_height': '12 دور'}]
        })
        self.assertNotIn('approved_floor_count', result)
        self.assertNotIn('approved_floor_count', result['parcels'][0])
        self.assertEqual(result['parcels'][0]['max_floors_height'], '12 دور')

        coverage_result = self.application_module._normalize_land_document_result({
            'parcels': [{'parcel_id': 'P-1', 'approved_coverage_ratio': 55, 'setbacks': 'أمامي 6م'}]
        })
        self.assertNotIn('approved_coverage_ratio', coverage_result)
        self.assertNotIn('approved_coverage_ratio', coverage_result['parcels'][0])

        regulatory = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'allowed_uses_restrictions': 'استخدام سكني',
                'parking_requirements': 'موقف لكل وحدة',
                'entrances_exits_requirements': 'مدخل سيارات منفصل',
            }]
        })
        restrictions = regulatory['parcels'][0]['allowed_uses_restrictions']
        self.assertIn('اشتراطات المواقف', restrictions)
        self.assertIn('اشتراطات المداخل والمخارج', restrictions)

        app_source = read_module_source('app.py')
        index_source = read_frontend_text()
        self.assertIn("resp_json.pop('approved_floor_count', None)", app_source)
        self.assertIn("resp_json.pop('approved_coverage_ratio', None)", app_source)
        self.assertIn('parking_requirements', app_source)
        self.assertIn('entrances_exits_requirements', app_source)
        self.assertIn("delete fields.approved_floor_count", index_source)
        self.assertIn("delete fields.approved_coverage_ratio", index_source)
        self.assertIn("'approved_floor_count'", index_source)

    def test_direction_and_coordinate_tables_are_separate_ai_outputs(self):
        index_source = read_frontend_text()
        self.assertIn('surveyCoordinatesPanel', index_source)
        self.assertIn('surveyDirectionsPanel', index_source)
        self.assertNotIn('addSurveyCoordinateButton', index_source)
        self.assertIn('data-key="survey_coordinates"', index_source)
        self.assertIn('data-key="directions_table"', index_source)
        self.assertIn("f.fieldKey === 'land_documents_files'", index_source)
        self.assertIn("analyzeButton.textContent = 'تحليل الكروكي والمستندات معًا'", index_source)
        self.assertNotIn('analyzeLandDocumentsButton', index_source)
        self.assertIn('regulation_text', index_source)
        self.assertIn('landAnalysisDiagnostics', index_source)
        self.assertIn('showLandAnalysisDiagnostics', index_source)
        self.assertIn('uncertaintyMarkers', index_source)
        self.assertNotIn('تمت قراءة جدولي التنظيم', index_source)

    def test_land_tables_survive_draft_round_trip_without_being_wiped(self):
        """The coordinate/direction tables live in hidden inputs as JSON strings, so the
        renderers must parse them back instead of replacing stored rows with empty ones."""
        index_source = read_frontend_text()
        self.assertIn('function parseStoredLandTable(value)', index_source)
        self.assertIn('const parsed = parseStoredLandTable(rows);', index_source)
        self.assertIn('if (hadValue && parsed === null) return;', index_source)
        self.assertIn('if (hadValue && parseStoredLandTable(value) === null) return;', index_source)
        # The destructive forms that silently dropped JSON strings must be gone.
        self.assertNotIn('const normalized = Array.isArray(rows) ? rows : [];', index_source)
        self.assertNotIn('Object.entries(value || {}).map(([direction, data])', index_source)

        client = self.app.test_client()
        coordinates = json.dumps(
            [{'parcel_id': 'P-1', 'point': '1', 'eastings': '510180.849',
              'northings': '2939234.840', 'source': 'regulation_table'}],
            ensure_ascii=False)
        directions = json.dumps(
            [{'direction': 'north', 'regulation_text': 'بطول 80.32م يحده شارع',
              'setback': '5م', 'source': 'regulation_table'}],
            ensure_ascii=False)
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'survey_coordinates': coordinates, 'directions_table': directions}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        draft_data = loaded.get_json()['draft']['draft_data']
        self.assertEqual(json.loads(draft_data['survey_coordinates'])[0]['eastings'], '510180.849')
        self.assertEqual(json.loads(draft_data['directions_table'])[0]['direction'], 'north')
        self.assertEqual(json.loads(draft_data['directions_table'])[0]['setback'], '5م')

    def test_land_analysis_is_persisted_but_not_shown_as_a_review_panel(self):
        """The conflicts/parcels panels were removed; the payload must still be saved because
        the directions table falls back to parcels[0].directions on reload."""
        index_source = read_frontend_text()
        self.assertIn('function storeLandDocumentAnalysis(', index_source)
        self.assertIn('landDocumentsAnalysisData', index_source)
        self.assertIn('parseStoredLandTable(source.land_documents_analysis)', index_source)
        # No visible review UI, and no raw JSON dumped at the user.
        self.assertNotIn('renderExtractedParcels', index_source)
        self.assertNotIn('renderLandDocumentConflicts', index_source)
        self.assertNotIn('القطع المكتشفة', index_source)
        self.assertNotIn('تعارضات تحتاج مراجعتك', index_source)
        self.assertNotIn('typeof item === \'string\' ? item : JSON.stringify(item)', index_source)
        self.assertNotIn('escapeHtml(JSON.stringify(parcel.confidence', index_source)
        # Conflicts are still requested so the model records disagreements instead of
        # silently picking a value, and they surface through the narrative summary.
        app_source = read_module_source('app.py')
        self.assertIn('"conflicts": [{"field": "", "description": ""}]', app_source)
        self.assertIn('_build_land_extraction_diagnostics', app_source)
        self.assertIn('إحداثيات التنظيم', app_source)
        self.assertIn('بموجب التنظيم', app_source)
        self.assertIn('"coordinate_tables"', app_source)
        self.assertIn('"regulation_coordinates"', app_source)
        self.assertNotIn('"severity": "high|medium|low"', app_source)

    def test_direction_setbacks_are_extracted_per_direction_and_stay_optional(self):
        """Each direction row carries its own setback: the model fills it only when the
        documents name one, the table column stays editable, and empty is a valid state."""
        index_source = read_frontend_text()
        self.assertIn('data-direction-field="setback"', index_source)
        self.assertIn('<th>الارتداد</th>', index_source)
        self.assertIn('setback: row.setback ?? row.setback_m', index_source)

        app_source = read_module_source('app.py')
        self.assertIn('"setback": ""', app_source)

        module = self.application_module
        directions = module._normalize_direction_map({
            'north': {'regulation_text': 'بطول 20م يحده شارع', 'setback': '5م'},
            'south': {},
        })
        self.assertEqual(directions['north']['setback'], '5م')
        self.assertFalse(directions['south'].get('setback'))
        # A direction whose only content is a setback still counts as extracted content.
        self.assertTrue(module._directions_have_content({'north': {'setback': '3م'}}))
        self.assertFalse(module._directions_have_content({'north': {}, 'south': {}}))

        rows = module._visual_concept_directions({
            'directions_table': json.dumps([
                {'direction': 'north', 'regulation_text': 'شارع 20م', 'setback': '5م'},
                {'direction': 'south', 'setback': '3م'},
                {'direction': 'east', 'regulation_text': '', 'setback': ''},
            ], ensure_ascii=False)
        })
        by_label = {row['direction']: row['regulation_text'] for row in rows}
        self.assertIn('الارتداد: 5م', by_label['شمال'])
        self.assertEqual(by_label['جنوب'], 'الارتداد: 3م')
        self.assertNotIn('شرق', by_label)

    def test_direction_setbacks_normalize_model_key_aliases_and_compass_text(self):
        """The model writes a direction's setback under several key names, and a
        compass-named value inside the setbacks narrative must reach the empty
        direction cell instead of leaving the table column blank."""
        module = self.application_module
        directions = module._normalize_direction_map({
            'north': {'setback_m': '5م'},
            'east': {'الارتداد': '2م'},
            'west': {'setbacks': '3م'},
        })
        self.assertEqual(directions['north']['setback'], '5م')
        self.assertEqual(directions['east']['setback'], '2م')
        self.assertEqual(directions['west']['setback'], '3م')

        parcel = {
            'directions': module._normalize_direction_map({'north': {}, 'south': {}, 'east': {}}),
            'setbacks': 'الارتداد الشمالي 5م، والارتداد الجنوبي 3م',
        }
        module._fill_direction_setbacks_from_text(parcel)
        self.assertEqual(parcel['directions']['north']['setback'], '5م')
        self.assertEqual(parcel['directions']['south']['setback'], '3م')
        self.assertFalse(parcel['directions']['east'].get('setback'))

        # A boundary length next to a direction word is not a setback.
        parcel = {
            'directions': module._normalize_direction_map({'north': {}}),
            'setbacks': 'الارتدادات غير مذكورة؛ يحد الأرض من الشمال شارع بطول 20م',
        }
        module._fill_direction_setbacks_from_text(parcel)
        self.assertFalse(parcel['directions']['north'].get('setback'))

        # And the summary field is composed from the direction table when the
        # model only filled the cells.
        parcel = {
            'directions': module._normalize_direction_map({
                'north': {'setback': '5م'}, 'south': {'setback': '3م'},
            }),
            'setbacks': '',
        }
        module._normalize_parcel_scalar_fields(parcel)
        self.assertEqual(parcel['setbacks'], 'شمال: 5م | جنوب: 3م')

    def test_land_documents_accumulate_across_picker_gestures(self):
        """A file input only holds the latest picker gesture: picking the licence
        then the croquis used to overwrite the metadata list, so the analysis saw
        a single document. The merge keeps earlier picks up to the cap."""
        index_source = read_frontend_text()
        self.assertIn('const LAND_DOCUMENTS_MAX = 4', index_source)
        self.assertIn("key === 'land_documents_files'", index_source)
        self.assertIn('storedIds.has(cachedId)', index_source)
        self.assertIn('storedIdentities.has(', index_source)
        self.assertIn('previousMeta.concat(', index_source)
        self.assertIn("slice(0, LAND_DOCUMENTS_MAX)", index_source)

    def test_extract_croquis_sends_every_uploaded_document_to_the_model(self):
        """The licence is analysed together with the croquis: every uploaded
        document must be rendered and labelled by kind in the final prompt."""
        module = self.application_module
        prepared = []

        def fake_prepare(document, budget=None, diagnostics=None):
            prepared.append((document['key'], document['filename']))
            return ([{'type': 'image_url',
                      'image_url': {'url': 'data:image/png;base64,x', 'detail': 'high'}}],
                    [], 1, 'image_direct')

        model_payload = {
            'parcels': [{'parcel_id': 'P-1', 'plot_number': '9991'}],
            'conflicts': [],
        }
        provider_response = {
            'choices': [{'finish_reason': 'stop',
                         'message': {'content': json.dumps(model_payload, ensure_ascii=False)}}]
        }
        calls = []

        def fake_call(system_prompt, user_content, max_tokens, **kwargs):
            calls.append(user_content)
            return provider_response, 9000, ''

        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module, '_prepare_document_vision_parts', side_effect=fake_prepare), \
                patch.object(module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(module, '_call_land_analysis_model', side_effect=fake_call):
            result = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'documents': [
                    {'fileData': 'data:application/pdf;base64,JVZERg==', 'filename': 'كروكي الأرض.pdf', 'mimeType': 'application/pdf'},
                    {'fileData': 'data:application/pdf;base64,JVZERg==', 'filename': 'رخصة البناء.pdf', 'mimeType': 'application/pdf'},
                ],
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual([item[1] for item in prepared], ['كروكي الأرض.pdf', 'رخصة البناء.pdf'])
        self.assertEqual([item[0] for item in prepared], ['croquis', 'building_license'])
        self.assertEqual(len(result.get_json()['documentProcessing']), 2)
        final_prompt = json.dumps(calls[-1], ensure_ascii=False)
        self.assertIn('كروكي الأرض.pdf', final_prompt)
        self.assertIn('رخصة البناء.pdf', final_prompt)
        self.assertIn('building_license', final_prompt)

    def test_project_draft_list_returns_metadata_without_payload(self):
        client = self.app.test_client()
        response = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'project_name': 'مسودة خفيفة',
                'tenantSlidesData': [{'html': 'x' * 5000}],
                'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/map.png'}},
            }
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        listed = client.get('/api/project-drafts', headers=self._headers(self.token_a))
        self.assertEqual(listed.status_code, 200, listed.get_json())
        draft = next(item for item in listed.get_json()['drafts'] if item['title'] == 'مسودة خفيفة')
        self.assertNotIn('draft_data', draft)
        self.assertTrue(draft['has_slides'])
        self.assertTrue(draft['has_maps'])
        self.assertGreater(draft['data_bytes'], 5000)

    def test_a_save_carrying_no_data_cannot_empty_a_stored_draft(self):
        """A draft is only ever emptied by DELETE.

        Saving used to store whatever arrived and answer success, and an absent ``draftData``
        became "{}". A payload with no ``draftId`` is applied to the row this actor updated most
        recently, so one mangled request emptied the project that was being worked on.
        """
        client = self.app.test_client()
        stored = {
            'draftId': 'draft-wipe-guard',
            'project_name': 'برج المشرق',
            'location_address': 'https://maps.google.com/?q=24,46',
            'approved_financial_area': '7012',
            'market_study_data': 'x' * 2000,
        }
        self.assertEqual(
            client.post('/api/project-draft', headers=self._headers(self.token_a),
                        json={'draftData': stored}).status_code, 200)

        def remaining():
            response = client.get('/api/project-draft/draft-wipe-guard',
                                  headers=self._headers(self.token_a))
            self.assertEqual(response.status_code, 200, response.get_json())
            return response.get_json()['draft']['draft_data']

        no_payload = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                 json={'status': 'draft'})
        self.assertEqual(no_payload.status_code, 400, no_payload.get_json())
        empty_payload = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                    json={'draftData': {}})
        self.assertEqual(empty_payload.status_code, 400, empty_payload.get_json())

        # A form that was rebuilt but never filled reports every field as an empty string.
        blanked = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'draftId': 'draft-wipe-guard', 'project_name': '', 'location_address': '',
                'approved_financial_area': '', 'market_study_data': '',
                'pageDrafts': {'project': {'status': 'draft'}}, 'map_styles': {}, 'map_type': '',
            }
        })
        self.assertEqual(blanked.status_code, 409, blanked.get_json())
        self.assertEqual(blanked.get_json()['error_code'], 'DRAFT_EMPTY_OVERWRITE')

        self.assertEqual(remaining()['project_name'], 'برج المشرق')
        self.assertEqual(remaining()['approved_financial_area'], '7012')

        # A save that names no draft lands on the newest one, so it must be refused too.
        unnamed = client.post('/api/project-draft', headers=self._headers(self.token_a),
                              json={'draftData': {'project_name': '', 'city': ''}})
        self.assertEqual(unnamed.status_code, 409, unnamed.get_json())
        self.assertEqual(remaining()['project_name'], 'برج المشرق')

    def test_project_form_blanks_are_not_collected_before_it_is_filled(self):
        """The form is built empty and filled afterwards, so its blank inputs must not be
        reported as the project's values while hydration has not completed."""
        index_source = read_frontend_text()
        self.assertIn('function tenantProjectFormIsFilled()', index_source)
        self.assertIn("form.dataset.projectFormFilled = ''", index_source)
        self.assertIn('markTenantProjectFormFilled();', index_source)
        self.assertIn('if (!tenantProjectFormIsFilled()) {', index_source)
        self.assertIn(
            'if (isBlankProjectValue(result[key]) && !isBlankProjectValue(tenantProjectData[key])) {',
            index_source)
        # The marker is written after hydration finishes, so a throw part-way leaves it unset.
        hydrate_body = index_source.split('function hydrateTenantProjectForm(data) {')[1]
        hydrate_body = hydrate_body.split('\n    function ')[0]
        self.assertLess(hydrate_body.index("form.querySelectorAll('[data-key]')"),
                        hydrate_body.index('markTenantProjectFormFilled();'))

    def test_an_unreassembled_chunked_reference_never_reaches_a_route(self):
        """The reassembly hook used to return silently when it could not read the reference, and
        the route then saw a request with no data at all."""
        client = self.app.test_client()
        refused = client.post('/api/project-draft', headers=self._headers(self.token_a),
                              json={'__chunked_body': {'id': 'a' * 12, 'total': 4, 'gzip': False}})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(refused.get_json()['error'], 'Missing uploaded body chunks')

        # The marker appearing inside ordinary content is not a reference.
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'draftId': 'draft-chunk-marker',
                          'project_idea': 'يشرح النص كيف يعمل __chunked_body في الحفظ'}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())

        # Every large save goes through this path, so the round trip has to keep working.
        payload = {'draftData': {'draftId': 'draft-chunked-save',
                                 'project_name': 'برج مجمّع من أجزاء',
                                 'project_idea': 'وصف طويل ' * 400}}
        wire = gzip.compress(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        parts = [wire[start:start + 12 * 1024] for start in range(0, len(wire), 12 * 1024)]
        upload_id = 'chunked-save-1'
        for index, part in enumerate(parts):
            uploaded = client.post('/api/body-chunk', headers=self._headers(self.token_a), json={
                'id': upload_id, 'idx': index, 'total': len(parts),
                'data': base64.b64encode(part).decode('ascii'),
            })
            self.assertEqual(uploaded.status_code, 200, uploaded.get_json())
        assembled = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                json={'__chunked_body': {'id': upload_id, 'total': len(parts),
                                                         'gzip': True}})
        self.assertEqual(assembled.status_code, 200, assembled.get_json())
        stored = client.get('/api/project-draft/draft-chunked-save',
                            headers=self._headers(self.token_a)).get_json()['draft']
        self.assertEqual(stored['draft_data']['project_name'], 'برج مجمّع من أجزاء')

    def test_missing_map_asset_does_not_regenerate_on_static_request(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.get('/uploads/maps/missing-map.png')
        self.assertEqual(response.status_code, 404)
        generate_maps.assert_not_called()

    def test_generate_slides_does_not_generate_maps_implicitly(self):
        client = self.app.test_client()
        generated = ['<div class="slide" style="width:1280px;height:720px">ok</div>']
        with patch.object(self.application_module, 'generate_all_slides', return_value=generated), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/generate-slides', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0},
                'slidePlan': {'slides': [{'title': 'خريطة', 'type': 'map_overview'}]},
                'images': {},
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        generate_maps.assert_not_called()

    def test_project_file_upload_is_tenant_scoped_and_stored_by_hash(self):
        client = self.app.test_client()
        response = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'croquis',
            'draftId': 'draft-file-test',
            'file': (io.BytesIO(b'%PDF-1.4 test document'), 'parcel.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201, response.get_json())
        file_id = response.get_json()['file']['id']
        with self.app.app_context():
            stored = db.get_project_file(self.tenant_a, file_id)
            other = db.get_project_file(self.tenant_b, file_id)
        self.assertIsNotNone(stored)
        self.assertIsNone(other)
        self.assertEqual(stored['file_type'], 'croquis')
        self.assertTrue(os.path.basename(stored['storage_path']).startswith(stored['sha256']))

    def test_project_file_preview_is_tenant_scoped_and_served_inline(self):
        """Uploaded deeds/site plans must be viewable in the app, but only by their tenant."""
        client = self.app.test_client()
        created = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'land_document',
            'file': (io.BytesIO(b'%PDF-1.4 preview me'), 'krooki.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(created.status_code, 201, created.get_json())
        file_id = created.get_json()['file']['id']

        served = client.get(f'/api/project-files/{file_id}', headers=self._headers(self.token_a))
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, 'application/pdf')
        self.assertIn(b'%PDF', served.data)
        # Inline so it can render in an iframe, and never sniffed into another type.
        self.assertNotIn('attachment', served.headers.get('Content-Disposition', ''))
        self.assertEqual(served.headers.get('X-Content-Type-Options'), 'nosniff')

        self.assertEqual(
            client.get(f'/api/project-files/{file_id}', headers=self._headers(self.token_b)).status_code,
            404)
        self.assertIn(client.get(f'/api/project-files/{file_id}').status_code, (401, 403))

        index_source = read_frontend_text()
        self.assertIn('async function openProjectFilePreview(', index_source)
        self.assertIn("'/api/project-files/' + encodeURIComponent(fileId)", index_source)
        self.assertIn('onclick="openProjectFilePreview(', index_source)

    def test_uploaded_slot_images_are_published_to_a_durable_url(self):
        """A client upload was previewed from a blob: URL and that URL was saved into the file.

        A blob: URL only resolves inside the tab that created it, so every image the client
        had uploaded rendered broken once the file was reopened, and the export shipped a
        reference the server could never read.
        """
        client = self.app.test_client()
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        created = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'visual_reference',
            'file': (io.BytesIO(png_bytes), 'cover.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(created.status_code, 201, created.get_json())
        file_id = created.get_json()['file']['id']

        published = client.post(f'/api/project-files/{file_id}/publish-image',
                                headers=self._headers(self.token_a))
        self.assertEqual(published.status_code, 200, published.get_json())
        url = published.get_json()['url']
        self.assertTrue(url.startswith('/uploads/creative/'), url)
        # The published copy is served without an Authorization header, which is the whole
        # point: it can sit in a saved draft and in an exported deck.
        self.assertEqual(client.get(url).status_code, 200)

        # Another tenant cannot publish a file it does not own.
        self.assertEqual(
            client.post(f'/api/project-files/{file_id}/publish-image',
                        headers=self._headers(self.token_b)).status_code, 404)

        # A blob: cover reaching the server falls back to the stored file instead of being used.
        with self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            fallback = self.application_module._visual_concept_cover_image(
                {'coverImage': 'blob:https://example.test/abc', 'coverFileId': file_id})
        self.assertTrue(fallback.startswith('data:image/'), fallback[:32])

        index_source = read_frontend_text()
        self.assertIn("'/api/project-files/' + encodeURIComponent(fileId) + '/publish-image'", index_source)
        self.assertIn('liveSlot().imageUrl = await publishProjectFileImageUrl(fileId);', index_source)
        self.assertIn('imageUrl: await publishProjectFileImageUrl(file.id)', index_source)
        self.assertIn('viewSlot.imageUrl = await publishProjectFileImageUrl(file.id);', index_source)
        # A stored blob: URL is dropped on load and republished from the file id.
        self.assertIn('const approved = durableImageUrl(slot.approvedImageUrl);', index_source)
        self.assertIn('const imageUrl = durableImageUrl(slot.imageUrl);', index_source)
        self.assertIn('const imageUrl = durableImageUrl(source.imageUrl || source.image_url);', index_source)
        self.assertIn('async function repairVisualConceptStoredImages()', index_source)
        self.assertIn('repairVisualConceptStoredImages();', index_source)
        self.assertNotIn('liveSlot().imageUrl = await getProjectFileObjectUrl(fileId)', index_source)

    def test_land_photos_are_optional_images_with_per_photo_descriptions(self):
        client = self.app.test_client()
        fields = client.get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        photo_field = next(field for field in fields if field['fieldKey'] == 'land_photos')
        self.assertFalse(photo_field['isRequired'])
        self.assertEqual(photo_field['sectionKey'], 'land_croquis')

        # PDFs are rejected for this slot because the UI renders them as thumbnails.
        rejected = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'land_image',
            'file': (io.BytesIO(b'%PDF-1.4 not a photo'), 'plan.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(rejected.status_code, 400, rejected.get_json())

        descriptions = [
            {'id': 'photo-1', 'originalName': 'front.jpg', 'description': 'الواجهة الشمالية'},
            {'id': 'photo-2', 'originalName': 'street.jpg', 'description': 'الشارع الغربي'},
        ]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'land_photos_file_ids': ['photo-1', 'photo-2'],
                          'land_photos_file_meta': descriptions}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        self.assertEqual(draft_data['land_photos_file_meta'][0]['description'], 'الواجهة الشمالية')

        index_source = read_frontend_text()
        self.assertIn('const LAND_PHOTOS_MAX = 4;', index_source)
        self.assertIn('function renderLandPhotos(', index_source)
        self.assertIn("input.dataset.projectFileType = 'land_image'", index_source)
        self.assertIn('function removeLandPhoto(', index_source)
        # Autosave re-uploads must not clear captions the client already typed.
        self.assertIn('previous?.description ? { ...file, description: previous.description } : file', index_source)

    def test_new_land_fields_split_identifiers_and_add_deed_date(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        by_key = {field['fieldKey']: field for field in fields}
        for key in ('plan_number', 'deed_date', 'facades_directions', 'land_photos'):
            self.assertIn(key, by_key)
            self.assertEqual(by_key[key]['sectionKey'], 'land_croquis')
        self.assertNotIn('subdivision_number', by_key)
        self.assertEqual(by_key['location_address']['sectionKey'], 'location')
        self.assertTrue(by_key['location_address']['isRequired'])
        for key in ('project_name', 'project_type', 'project_mixed_components', 'project_subtype', 'project_stage', 'project_logo',
                    'project_idea', 'project_level', 'target_audience', 'activity_class'):
            self.assertEqual(by_key[key]['sectionKey'], 'basic')
        self.assertEqual(by_key['project_mixed_components']['fieldLabel'], 'أنواع المشروع متعدد الاستخدامات')
        for key in ('project_goal', 'initial_features', 'initial_strengths'):
            self.assertNotIn(key, by_key)
        self.assertEqual(by_key['project_type']['fieldOptions'], [
            'سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'
        ])
        self.assertEqual(by_key['city']['sectionKey'], 'location')
        self.assertEqual(by_key['district']['sectionKey'], 'location')
        self.assertEqual(by_key['plot_number_croquis']['fieldLabel'], 'رقم القطعة')
        self.assertEqual(by_key['deed_date']['fieldLabel'], 'تاريخ الصك')
        self.assertEqual(by_key['building_ratio_coverage']['fieldLabel'], 'نسبة البناء والتغطية')
        self.assertEqual(by_key['setbacks']['fieldLabel'], 'الارتدادات')
        self.assertEqual(by_key['max_floors_height']['fieldType'], 'textarea')
        self.assertEqual(by_key['allowed_uses']['fieldLabel'], 'الاستخدامات المسموحة')
        self.assertEqual(by_key['regulatory_constraints']['fieldLabel'], 'القيود التنظيمية')
        index_source = read_frontend_text()
        self.assertNotIn('locationAddressMirror', index_source)
        self.assertNotIn('syncLocationAddressMirror', index_source)
        self.assertIn('geocodeTenantLocationLink', index_source)
        # City and district are editable in the location section — the map fill is a
        # starting value, not a lock — while the market study keeps read-only mirrors
        # fed from those same inputs, so site & maps stays the single edit point.
        self.assertNotIn("if (f.fieldKey === 'city' || f.fieldKey === 'district')", index_source)
        self.assertNotIn("input.title = 'تُملأ تلقائيًا من الموقع والخرائط'", index_source)
        self.assertNotIn('location-derived-input', index_source)
        self.assertIn('applyCityDistrictToForm(data.city, data.district, true)', index_source)
        self.assertIn('cityMirror.readOnly = true', index_source)
        self.assertIn('districtMirror.readOnly = true', index_source)
        self.assertIn("['city', 'district'].forEach", index_source)
        self.assertIn('syncMarketLocationMirrors', index_source)
        self.assertIn('includeMapContext: true', index_source)
        self.assertIn('function renderAllowedUsesStatusNote(status)', index_source)
        self.assertIn("id = 'allowedUsesStatusNote'", index_source)
        self.assertIn("استخدام نوع المشروع غير مسموح حسب الاشتراطات", index_source)
        self.assertIn('function resolveLandUseStatus(projectType, allowedUses)', index_source)
        self.assertIn('function refreshAllowedUsesStatusNote()', index_source)
        self.assertIn("قائمة الاستخدامات المسموحة تنظيميًا", read_module_source('db.py'))
        self.assertIn('function slimLandAnalysisSiteContext(context)', index_source)
        self.assertIn('siteContext: slimLandAnalysisSiteContext(projectContext)', index_source)
        self.assertNotIn('siteContext: projectContext', index_source)
        self.assertIn("sectionKey === 'location'", index_source)
        self.assertIn('locationLat: projectContext.location_lat', index_source)
        self.assertIn("f.fieldType === 'textarea' || f.fieldKey === 'location_address' || f.fieldKey === 'project_type' ? ' full'", index_source)

    def test_uploaded_land_documents_are_restored_as_server_metadata_after_refresh(self):
        client = self.app.test_client()
        metadata = [{'id': 'file-a', 'originalName': 'permit.pdf', 'fileSize': 1024}]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'land_documents_files_file_ids': ['file-a'], 'land_documents_files_file_meta': metadata}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        self.assertEqual(loaded.status_code, 200, loaded.get_json())
        draft_data = loaded.get_json()['draft']['draft_data']
        self.assertEqual(draft_data['land_documents_files_file_ids'], ['file-a'])
        self.assertEqual(draft_data['land_documents_files_file_meta'], metadata)

    def test_browser_history_tracks_pages_sections_and_internal_tabs(self):
        index_source = read_frontend_text()
        self.assertIn('function syncTenantBrowserHistory', index_source)
        self.assertIn('function showSection(sectionKey, fromHistory = false)', index_source)
        self.assertIn('function setGlobalRailTab(tab, fromHistory = false)', index_source)
        self.assertIn("syncTenantBrowserHistory('tenantProjectPage', { activeSection: sectionKey }, fromHistory)", index_source)
        self.assertIn("window.history[method](state, '', url)", index_source)

    def test_location_analysis_runs_only_from_explicit_button(self):
        index_source = read_frontend_text()
        self.assertIn("btn.onclick = () => analyzeTenantSite();", index_source)
        self.assertNotIn("addressInput.addEventListener('paste'", index_source)
        self.assertNotIn("addressInput.addEventListener('blur'", index_source)
        address_block = index_source.split("if (f.fieldKey === 'location_address') {", 1)[1].split("if (f.fieldKey === 'location_lat')", 1)[0]
        self.assertNotIn("addEventListener('paste'", address_block)
        self.assertNotIn("addEventListener('blur'", address_block)
        self.assertNotIn('geocodeTenantLocationLink(', address_block)

    def test_financial_visibility_has_native_hidden_guard_for_optional_sections(self):
        index_source = read_frontend_text()
        self.assertIn('element.hidden = !visible', index_source)
        self.assertIn("setConditionalVisibility('graceDetails', graceOn)", index_source)
        self.assertIn("setConditionalVisibility('graceScheduleWrap', scheduledGrace)", index_source)
        self.assertIn('const modeFlags = projectModeFlags();', index_source)
        self.assertIn('const targetCarry = profit * carryRate', index_source)
        self.assertIn("setConditionalVisibility('fundExitPerformanceGrid', feesOn)", index_source)

    def test_croquis_expiry_date_field_is_retired(self):
        """Retiring a prebuilt field means REMOVED_PREBUILT_FIELDS, so existing tenants lose it too,
        and the model must stop being asked for a value nothing will display."""
        self.assertIn('croquis_expiry_date', db.REMOVED_PREBUILT_FIELDS)
        self.assertNotIn('croquis_expiry_date', {field['key'] for field in db.PREBUILT_FIELDS})

        # Gone from the tenant's active field list, not just from the defaults.
        client = self.app.test_client()
        fields = client.get('/api/fields', headers=self._headers(self.token_a)).get_json()
        keys = {item['fieldKey'] for item in (fields.get('fields') or [])}
        self.assertNotIn('croquis_expiry_date', keys)

        # The extraction prompt, the alias map, the summary row and the parcel mapping are clean,
        # so no tokens are spent on it and no orphan value is stored.
        app_source = read_module_source('app.py')
        self.assertNotIn('croquis_expiry_date', app_source)
        self.assertNotIn('expiry_date', app_source)
        self.assertNotIn("'croquis_validity_dates'", app_source)

        # The validity badge and its date parsing went with the field.
        index_source = read_frontend_text()
        self.assertNotIn('croquis_expiry_date', index_source)
        self.assertNotIn('croquisExpiryBadge', index_source)

    def test_retired_location_fields_leave_the_backend(self):
        """land_area, built_area, building_system, infrastructure and secondary_roads were
        deleted from the location section — the backend must stop seeding, serving and
        writing them, or the section keeps billing and storing fields nobody can see."""
        retired = {'land_area', 'built_area', 'building_system', 'infrastructure', 'secondary_roads'}
        self.assertTrue(retired <= db.REMOVED_PREBUILT_FIELDS)
        self.assertFalse(retired & {field['key'] for field in db.PREBUILT_FIELDS})

        client = self.app.test_client()
        fields = client.get('/api/fields', headers=self._headers(self.token_a)).get_json()
        keys = {item['fieldKey'] for item in (fields.get('fields') or [])}
        self.assertFalse(retired & keys)

        module = self.application_module
        app_source = read_module_source('app.py')
        self.assertFalse(retired & set(module.LAND_ANALYSIS_SITE_CONTEXT_KEYS))
        # The four retired scalars left the site-analysis whitelist entirely; land_area
        # survives only as a stored-value fallback inside the visual-concept readers.
        for key in ('built_area', 'building_system', 'infrastructure', 'secondary_roads'):
            self.assertNotIn(key, app_source)
        self.assertNotIn("'land_area', 'built_area'", app_source)

        index_source = read_frontend_text()
        # Quoted keys only: 'infrastructure_cost' is a live financial field and must not
        # false-positive the retirement check for the deleted 'infrastructure' field.
        for key in ('built_area', 'building_system', 'infrastructure', 'secondary_roads'):
            self.assertNotIn(f"'{key}'", index_source)
            self.assertNotIn(f'"{key}"', index_source)
        # The ##land_area## template token stays but is fed by the croquis fields —
        # the retired project field must not be read anywhere.
        self.assertNotIn('projectData.land_area', index_source)

    def test_land_documents_upload_on_selection_not_on_save(self):
        """The upload used to run inside collectTenantFormData, which only executed from the
        autosave. Once autosave was removed the files sat on "saving" forever and the analyse
        button saw no file ids to send."""
        index_source = read_frontend_text()

        # Choosing a file must upload it, the way land photos already did.
        self.assertIn('uploadLandDocuments(input);', index_source)
        self.assertIn('async function uploadLandDocuments(input)', index_source)
        self.assertIn("uploadTenantProjectFileInput(input, 'land_documents_files')", index_source)

        # The old change handler only drew placeholders and waited for a save that never came.
        self.assertNotIn(
            "renderLandDocumentsUploadState(Array.from(input.files).map(file => ({ originalName: file.name, fileSize: file.size, status: 'pending' })));\n                triggerAutoSaveDraft();",
            index_source)

        # And the card must not claim an autosave that no longer exists.
        self.assertNotIn('جاري الحفظ تلقائيًا', index_source)
        self.assertIn("'جاري الرفع...'", index_source)

    def test_uploaded_land_documents_can_be_removed(self):
        """A wrongly uploaded deed or croquis had no way out: the card offered preview only."""
        index_source = read_frontend_text()

        self.assertIn('function removeLandDocument(fileId)', index_source)
        self.assertIn("onclick=\"removeLandDocument(\\'", index_source)

        # Both the metadata list and the id list must be updated, because the analysis reads the
        # metadata list to decide which files to send to the model.
        self.assertIn('tenantProjectData.land_documents_files_file_meta = meta;', index_source)
        self.assertIn('tenantProjectData.land_documents_files_file_ids = meta.map(item => item.id);',
                      index_source)

        # Clearing the cached signatures lets the same file be re-selected after a mistake.
        self.assertIn("document.querySelector('#tenantProjectForm [data-key=\"land_documents_files\"]')",
                      index_source)
        self.assertIn('delete input.dataset.uploadSignatures;', index_source)

        # Removing a file must re-render, and persist the change.
        self.assertIn('renderLandDocumentsUploadState(meta);', index_source)

    def test_empty_places_result_is_not_reported_as_a_provider_error(self):
        """Places API (New) answers a valid search that matches nothing with HTTP 200 and "{}".
        Calling that an error turned a quiet area into "invalid response" and hid the caller's own
        "no landmarks found" message, which is only reachable on success."""
        import maps_service

        class _Response:
            status_code = 200
            def json(self):
                return {}

        with patch.object(maps_service, '_has_api_key', return_value=True), \
             patch.object(maps_service, '_get_api_key', return_value='k'), \
             patch.object(maps_service.requests, 'post', return_value=_Response()):
            result = maps_service.get_nearby_landmarks(21.5, 39.2, radius=20000)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['landmarks'], [])
        self.assertIsNone(result.get('error_code'))

        # A genuinely malformed 200 body is still an error.
        class _Garbage(_Response):
            def json(self):
                return {'unexpected': 'shape'}

        with patch.object(maps_service, '_has_api_key', return_value=True), \
             patch.object(maps_service, '_get_api_key', return_value='k'), \
             patch.object(maps_service.requests, 'post', return_value=_Garbage()):
            broken = maps_service.get_nearby_landmarks(21.5, 39.2, radius=20000)
        self.assertFalse(broken['success'])
        self.assertEqual(broken['error_code'], 'GOOGLE_PLACES_INVALID_RESPONSE')

        # The reason must survive on screen, not only in a toast that disappears.
        index_source = read_frontend_text()
        self.assertIn('id="siteAnalysisWarnings"', index_source)
        self.assertIn('const reasons = [data.landmarksWarning, data.cityLandmarksWarning].filter(Boolean);',
                      index_source)
        self.assertIn('تم تحليل بيانات الموقع، لكن تعذر جلب بعض المعالم', index_source)

    def test_financial_pdf_has_no_raw_identifiers_or_json(self):
        """Section 12 used to dump the whole projection object, so schedule arrays landed in the
        client PDF as raw JSON under English keys, and table headers printed internal names."""
        model = {
            'inputs': {'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 7000,
                       'builtUpAreaAbove': 60000, 'financeEnabled': 'yes', 'fundEnabled': 'no',
                       'fundFeesEnabled': 'no', 'externalEnabled': 'no', 'exitEnabled': 'no'},
            'tables': {
                'financeDrawTable': [{'year': 1, 'drawPct': 25}],
                'financeRepaymentTable': [{'year': 5, 'repaymentPct': 10}],
                'scheduleTable': [{'name': 'الأساسات', 'year': 1, 'costPct': 30, 'devPct': 30}],
                'cashflowTable': [{'year': 1, 'phase': 'تطوير', 'saleRevenue': 0, 'opex': 100,
                                   'final': -500, 'cumulative': -500}],
            },
            'projection': {
                'projectCost': 500000000, 'roi': 0.42, 'projectIrr': 0.18, 'equityIrr': 0.22,
                # These two are what leaked as JSON; they belong to section 8 as tables.
                'financePlan': [{'year': 4, 'drawPct': 25}],
                'financeRepaymentPlan': [{'year': 8, 'repaymentPct': 10}],
                'projected': [1, 2], 'cashflows': [4, 5], 'modeFlags': {'sales': True},
                'areaState': {'valid': True},
                # Echoed inputs already shown in sections 1 and 2.
                'landArea': 7000, 'developerRate': 10,
            },
        }
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع', model, {}, self.tenant_a)

        # No structured value may be stringified into a row.
        self.assertNotIn('financePlan', html)
        self.assertNotIn('financeRepaymentPlan', html)
        self.assertNotIn('"drawPct"', html)
        self.assertNotIn('[{', html)

        # No internal identifier may be used as a visible header, allowing only accepted business acronyms (ROI, NOI).
        self.assertEqual(set(re.findall(r'<th>([A-Za-z]\w*)</th>', html)) - {'ROI', 'NOI'}, set())

        # Curated results with business domain acronyms, and the schedules still render as real tables in section 8.
        self.assertIn('12. النتائج المالية', html)
        self.assertIn('إجمالي تكلفة المشروع', html)
        self.assertIn('500,000,000', html)
        self.assertIn('42%', html)
        self.assertIn('18%', html)
        self.assertIn('Project IRR', html)
        self.assertIn('نسبة السحب %', html)
        self.assertIn('صافي تدفق المشروع', html)
        # Echoed inputs are no longer repeated in the results summary.
        self.assertNotIn('developerRate', html)

    def test_financial_pdf_prints_the_screen_verbatim_in_tables(self):
        """The export is the study as the screen shows it, only laid out as tables.

        The server used to rebuild the report from its own label map, so «هل وحدات المشروع بيعية
        أم تأجيرية؟» printed as «طبيعة الإيرادات» and its value printed as the raw option id
        «mixed», and a light branding colour painted the label column unreadable.
        """
        model = {
            'inputs': {'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 70000,
                       'financeEnabled': 'no', 'fundEnabled': 'no', 'fundFeesEnabled': 'no',
                       'externalEnabled': 'no', 'exitEnabled': 'no', 'builtUpAreaAbove': 100000},
            'tables': {}, 'projection': {},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '1. طبيعة وحدات المشروع'},
                {'type': 'fields', 'rows': [['هل وحدات المشروع بيعية أم تأجيرية؟', 'مختلطة: بيعية وتأجيرية'],
                                            ['حالة الأرض', 'مستأجرة ولا تدخل ضمن تكلفة المشروع']]},
                {'type': 'heading', 'level': 2, 'text': '9. التمويل'},
                {'type': 'heading', 'level': 3, 'text': 'خطة سحب التمويل'},
                {'type': 'table', 'headers': ['سنة السحب', 'نسبة السحب من التسهيل %'], 'rows': [['1', '25%']]},
                {'type': 'fields', 'rows': [['صافي تدفق المشروع', '-13,125,000'], ['فترة الاسترداد', '4 سنة']]},
            ]},
        }
        branding = {'primary_color': '#EAF2F8', 'secondary_color': '#F0E9DF', 'accent_color': '#FFFFFF'}
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع مالي', model, branding, self.tenant_a)

        # Screen wording, screen values — nothing renamed, nothing reformatted, nothing dropped.
        self.assertIn('هل وحدات المشروع بيعية أم تأجيرية؟', html)
        self.assertIn('مختلطة: بيعية وتأجيرية', html)
        self.assertIn('مستأجرة ولا تدخل ضمن تكلفة المشروع', html)
        self.assertIn('<th>نسبة السحب من التسهيل %</th>', html)
        self.assertIn('25%', html)
        self.assertNotIn('mixed', html)
        self.assertNotIn('leased', html)
        self.assertNotIn('طبيعة الإيرادات', html)

        # A sub-heading keeps its block title, and every value sits in a table cell.
        self.assertLess(html.index('9. التمويل'), html.index('خطة سحب التمويل'))
        self.assertNotIn('<p>مختلطة', html)

        # A figure is an LTR run: in an RTL cell the bidi algorithm moved the leading minus to the
        # right of the digits, so «-13,125,000» printed as «13,125,000-».
        self.assertIn('<td dir="ltr">-13,125,000</td>', html)
        self.assertIn('<td dir="ltr">25%</td>', html)
        # Text that happens to start with a figure stays in the cell's own direction.
        self.assertIn('<td>4 سنة</td>', html)
        self.assertIn('<td>مستأجرة ولا تدخل ضمن تكلفة المشروع</td>', html)
        index_source = read_frontend_text()
        self.assertIn('unicode-bidi: plaintext;', index_source)
        self.assertIn('td{unicode-bidi:plaintext}', index_source)

        # The branding palette no longer paints the report, so a light tenant colour cannot
        # print pale text on a pale tint.
        for colour in branding.values():
            self.assertNotIn(colour, html)

        # The fallback engine renders the same parts rather than the old label map.
        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, 'screen.pdf')
            with self.app.app_context():
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, output)
            self.assertTrue(self.application_module._financial_pdf_has_text(output, minimum=20))

        # The client is what supplies those parts, and only for the export.
        self.assertIn('function collectFinancialStudyReport()', index_source)
        self.assertIn('model.report = collectFinancialStudyReport();', index_source)
        self.assertNotIn('report: collectFinancialStudyReport()', index_source)
        # Selected option text, not the option id, and hidden inputs stay out.
        self.assertIn("if (control.tagName === 'SELECT') return financialReportText(control.selectedOptions?.[0])",
                      index_source)
        self.assertIn("FINANCIAL_REPORT_SKIP_COLUMNS = new Set(['ترتيب / حذف', 'ترتيب', 'حذف', 'مرتبط بمكون'])", index_source)

    def test_financial_decimals_and_pdf_values_use_one_decimal_and_thousands_separators(self):
        module = self.application_module
        self.assertEqual(module._financial_report_format_number(1234567.26, 'projectCost'), '1,234,567.3')
        self.assertEqual(module._financial_report_format_number(1234567, 'projectCost'), '1,234,567')
        self.assertEqual(module._financial_report_format_number(0.18254, 'projectIrr'), '18.3%')
        self.assertEqual(module._financial_report_format_number(6.55, 'payback'), '6.6 سنة')
        self.assertEqual(module._financial_report_format_number(2027, 'year'), '2027')
        self.assertEqual(module._financial_report_format_number(1234, 'units'), '1,234')
        self.assertEqual(module._financial_report_format_display('0500000000', 'رقم الهاتف'), '0500000000')

        model = {
            'inputs': {
                'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 70000,
                'builtUpAreaAbove': 100000, 'financeEnabled': 'no', 'fundEnabled': 'no',
                'fundFeesEnabled': 'no', 'externalEnabled': 'no', 'exitEnabled': 'no',
            },
            'tables': {},
            'projection': {},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
                {'type': 'fields', 'rows': [
                    ['إجمالي تكلفة الاستثمار', '1234567.26'],
                    ['Project IRR', '18.256%'],
                ]},
                {'type': 'table', 'headers': ['السنة', 'إجمالي الإيرادات', 'نسبة الإشغال %'],
                 'rows': [['2027', '9876543.26', '87.26%']]},
            ]},
        }
        with self.app.app_context():
            html = module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
        for expected in ('1,234,567.3', '18.3%', '9,876,543.3', '87.3%'):
            self.assertIn(expected, html)
        self.assertIn('<td dir="ltr">2027</td>', html)
        self.assertNotIn('2,027', html)

        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, 'grouped.pdf')
            with self.app.app_context():
                module.generate_financial_pdf_from_model('مشروع مالي', model, output)
            import fitz
            document = fitz.open(output)
            try:
                text = '\n'.join(page.get_text() for page in document)
            finally:
                document.close()
            for expected in ('1,234,567.3', '9,876,543.3', '87.3%'):
                self.assertIn(expected, text)
            self.assertNotIn('2,027', text)

        index_source = read_frontend_text()
        self.assertIn('function roundFinancialResult(value)', index_source)
        self.assertIn('maximumFractionDigits: hasFraction ? 1 : 0', index_source)
        self.assertIn('roundFinancialSavedResults(window.__financialProjection || {})', index_source)

    def test_financial_clarifications_are_manual_optional_and_omitted_when_empty(self):
        module = self.application_module
        base_inputs = {
            'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 70000,
            'builtUpAreaAbove': 100000, 'financeEnabled': 'no', 'fundEnabled': 'no',
            'fundFeesEnabled': 'no', 'externalEnabled': 'no', 'exitEnabled': 'no',
        }
        with self.app.app_context():
            blank_html = module.build_financial_report_html(
                'مشروع مالي', {'inputs': {**base_inputs, 'financialClarifications': ''}}, {}, self.tenant_a)
            filled_html = module.build_financial_report_html(
                'مشروع مالي', {'inputs': {
                    **base_inputs, 'financialClarifications': 'CLIENT-NOTE-731\nدفعة مرتبطة باعتماد العميل'
                }}, {}, self.tenant_a)
            blank_screen_html = module.build_financial_report_html('مشروع مالي', {
                'inputs': base_inputs,
                'report': {'parts': [
                    {'type': 'heading', 'level': 2, 'text': '15. الإيضاحات'},
                    {'type': 'fields', 'rows': [['الإيضاحات', '']]},
                ]},
            }, {}, self.tenant_a)

        self.assertNotIn('15. الإيضاحات', blank_html)
        self.assertNotIn('15. الإيضاحات', blank_screen_html)
        self.assertIn('15. الإيضاحات', filled_html)
        self.assertIn('CLIENT-NOTE-731', filled_html)
        self.assertIn('white-space:pre-wrap', filled_html)

        screen_model = {
            'inputs': base_inputs,
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '15. الإيضاحات'},
                {'type': 'fields', 'rows': [['الإيضاحات', 'CLIENT-NOTE-731']]},
            ]},
        }
        fallback_model = {'inputs': {
            **base_inputs, 'financialClarifications': 'CLIENT-NOTE-731\nدفعة مرتبطة باعتماد العميل'
        }}
        with tempfile.TemporaryDirectory() as folder:
            import fitz
            for name, pdf_model in (('screen', screen_model), ('fallback', fallback_model)):
                output = os.path.join(folder, name + '-clarifications.pdf')
                with self.app.app_context():
                    module.generate_financial_pdf_from_model('مشروع مالي', pdf_model, output)
                document = fitz.open(output)
                try:
                    text = '\n'.join(page.get_text() for page in document)
                finally:
                    document.close()
                self.assertIn('CLIENT-NOTE-731', text)

        index_source = read_frontend_text()
        self.assertIn('<textarea id="financialClarifications"', index_source)
        self.assertIn('#section-financial-calc #financialClarifications {', index_source)
        self.assertIn('font-size: 13px !important;', index_source.split('#section-financial-calc #financialClarifications {', 1)[1].split('}', 1)[0])
        self.assertIn('.financial-clarifications{white-space:pre-wrap', index_source)
        self.assertIn('font-size:10px', index_source.split('.financial-clarifications{', 1)[1].split('}', 1)[0])
        self.assertNotIn('id="clarificationsTable"', index_source)
        self.assertNotIn('function renderClarifications(facts)', index_source)

    def test_financial_pdf_keeps_revenue_items_without_linked_component_column(self):
        module = self.application_module
        compound = 'مساحة مبنية 1234567.26 م² وقيمة 7654321 ريال'
        self.assertEqual(
            module._financial_report_format_display(compound, 'تفاصيل الاستثمار'),
            'مساحة مبنية 1,234,567.3 م² وقيمة 7,654,321 ريال',
        )
        screenshot_values = (
            ('إيراد أول سنة تشغيل', '69192152.4', '69,192,152.4'),
            ('NOI أول سنة تشغيل', '27676861', '27,676,861'),
            ('إيرادات التشغيل عند 100% إشغال', '115320254', '115,320,254'),
            ('المصروفات عند 100% إشغال', '69192152.4', '69,192,152.4'),
            ('NOI عند 100% إشغال', '46128101.6', '46,128,101.6'),
        )
        for label, value, expected in screenshot_values:
            self.assertEqual(module._financial_report_format_display(value, label), expected)
        report_model = {
            'inputs': {'unitRevenueMode': 'mixed'},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '4. بنود الإيرادات'},
                {'type': 'table', 'headers': ['اسم الإيراد', 'مرتبط بمكون', 'القيمة'],
                 'rows': [['REVENUE-LABEL', 'LINKED-COMPONENT-HIDDEN', '1234567.26']]},
                {'type': 'heading', 'level': 2, 'text': '12. ملخص النتائج المالية'},
                {'type': 'fields', 'rows': (
                    [['إجمالي الاستثمار', 'TOTAL 1234567.26']]
                    + [[label, value] for label, value, _expected in screenshot_values]
                )},
            ]},
        }
        fallback_model = {
            'inputs': {'unitRevenueMode': 'mixed'},
            'tables': {'revenueTable': [{
                'name': 'REVENUE-LABEL', 'component': 'LINKED-COMPONENT-HIDDEN',
                'price': 1234567.26,
            }]},
        }
        with self.app.app_context():
            report_html = module.build_financial_report_html('مشروع مالي', report_model, {}, self.tenant_a)
            fallback_html = module.build_financial_report_html('مشروع مالي', fallback_model, {}, self.tenant_a)
        for html in (report_html, fallback_html):
            self.assertIn('4. بنود الإيرادات', html)
            self.assertIn('REVENUE-LABEL', html)
            self.assertNotIn('مرتبط بمكون', html)
            self.assertNotIn('LINKED-COMPONENT-HIDDEN', html)
            self.assertIn('1,234,567.3', html)
        self.assertIn('TOTAL 1,234,567.3', report_html)
        for _label, _value, expected in screenshot_values:
            self.assertIn(expected, report_html)

        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, 'with-revenue.pdf')
            with self.app.app_context():
                module.generate_financial_pdf_from_model('مشروع مالي', report_model, output)
            import fitz
            document = fitz.open(output)
            try:
                text = '\n'.join(page.get_text() for page in document)
            finally:
                document.close()
            normalized_text = text.replace('\xa0', ' ')
            self.assertIn('REVENUE-LABEL', normalized_text)
            self.assertNotIn('LINKED-COMPONENT-HIDDEN', normalized_text)
            self.assertIn('TOTAL 1,234,567.3', normalized_text)

        index_source = read_frontend_text()
        self.assertIn("<h3>4. بنود الإيرادات</h3>${reportTableSnapshot('revenueTable'", index_source)
        self.assertIn("'مرتبط بمكون'", index_source.split('FINANCIAL_REPORT_SKIP_COLUMNS', 1)[1][:180])

    def test_cashflow_column_tints_do_not_override_the_table_header(self):
        """The cf-* classes also sit on the <th> so whole columns can be hidden by project mode.
        An unscoped class rule outranks "#section-financial-calc th" on specificity, which left
        those headers tinted with white text on them."""
        index_source = read_frontend_text()
        for group in ('sales', 'rental', 'grace', 'fund', 'finance'):
            self.assertNotIn(f'#section-financial-calc .cf-{group} {{', index_source,
                             f'.cf-{group} must be scoped to td')
            self.assertIn(f'#section-financial-calc td.cf-{group} {{', index_source)
        # The classes must stay on the headers: column visibility depends on them.
        self.assertIn('<th class="cf-sales">', index_source)
        self.assertIn("setConditionalSelector('.cf-sales', flags.sales)", index_source)
        # Any other class placed on a th must be scoped for both th and td, as lt-* already is.
        header_classes = set(re.findall(r'<th[^>]*class="([^"]+)"', index_source))
        self.assertEqual(header_classes,
                         {'cf-sales', 'cf-rental', 'cf-grace', 'cf-fund', 'cf-finance',
                          'lt-dist', 'lt-dur', 'lt-map-toggle', 'lt-actions'},
                         'a new class on a <th> needs its background rule scoped to td')

    def test_grouped_classification_dropdowns_fill_their_field(self):
        """`.project-choice-grid` is a flex row. The grouped fields wrap each dropdown in its own
        div, and a flex item shrinks to fit, so the dropdown's `width:100%` resolved against that
        shrunken box: «الأنواع الفرعية للمشروع» and «الفئة المستهدفة» rendered as a narrow box and
        their menus broke every option onto two lines."""
        index_source = read_frontend_text()
        self.assertIn('.project-choice-grid>div {\n      flex: 1 1 100%;', index_source)
        # Those are the wrappers that need it, and the dropdown still spans whatever holds it.
        self.assertIn("'<div style=\"margin-top:10px\"><label>' + (showSubtypeLabels", index_source)
        self.assertIn("return '<div style=\"margin-top:10px\"><label>' + label + subtypeText +",
                      index_source)
        self.assertIn('.project-multi-select {\n      position: relative;\n      width: 100%;',
                      index_source)

    def test_slide_preview_does_not_resize_generated_main_frames(self):
        """Generated slides use semantic main elements for absolute content frames. A global
        `main { width:100% }` rule makes frames with right/left insets overflow in the preview,
        even though the export has no application stylesheet and remains correct."""
        index_source = read_frontend_text()
        self.assertNotIn('\n    main {', index_source)
        self.assertIn('.tenant-app > main {\n      width: 100%', index_source)

    def test_slide_preview_tables_do_not_inherit_the_app_table_minimum(self):
        """Generated slide tables can sit in a narrow column. The app-wide 850px minimum made
        those tables overflow the preview and clip content, while exports remained correct."""
        index_source = read_frontend_text()
        self.assertIn('.tenant-slide-stage .slide table {\n      min-width: 0;', index_source)

    def test_slide_preview_uses_one_canvas_scale_only(self):
        """The preview stage scales the complete slide canvas. A second content transform
        made some slides visibly shorter than their exported versions and clipped headings."""
        index_source = read_frontend_text()
        start = index_source.index('function autoFitSlideContent(stage)')
        end = index_source.index('function collectSlideTextNodes(root)', start)
        fit_source = index_source[start:end]
        canvas_start = index_source.index('function tenantSlideCanvasDimensions(slide)')
        canvas_source = index_source[canvas_start:start]
        self.assertIn("slide.style.width = canvas.width + 'px';", fit_source)
        self.assertIn("slide.style.height = canvas.height + 'px';", fit_source)
        self.assertIn("const defaultHeight = ratio === '4:3' ? 960 : 720;", canvas_source)
        self.assertIn("stage.style.setProperty('--stage-h'", fit_source)
        self.assertIn('const isLegacyAutoFit =', fit_source)
        self.assertNotIn("contentBox.style.transform = 'scale('", fit_source)
        self.assertNotIn('const targetH = 720;', fit_source)

    def test_ui_contains_no_emojis_or_icon_glyphs(self):
        """Product rule: the app ships no emojis and no icon glyphs, including arrows used as
        button labels. Generated slides are covered separately by the icon stripper."""
        pictographs = re.compile(
            '[\u2190-\u21ff\u2300-\u23ff\u25a0-\u27bf\u2b00-\u2bff\ufe0f'
            '\U0001f000-\U0001faff]'
        )
        # The shell plus its styles and scripts is the whole UI; the prompt files tell the
        # model what to produce, so an emoji there teaches it to emit one.
        frontend_names = (
            ['index.html']
            + ['assets/css/%s' % str(p.relative_to(ROOT / 'assets' / 'css')).replace('\\', '/')
               for p in sorted((ROOT / 'assets' / 'css').rglob('*.css'))]
            + [f'assets/js/{name}' for name in FRONTEND_JS_ORDER])
        for name in frontend_names + ['slide_engine.py', 'design_templates.py', 'app.py']:
            source = read_module_source(name)
            found = sorted({match.group() for match in pictographs.finditer(source)})
            self.assertEqual(found, [], f'{name} still contains icon glyphs: {found}')

        # No icon libraries. SVG is allowed only for genuine data rendering:
        # the favicon, the map polygon overlay, and the super-admin dashboard
        # charts (sparkline/line/donut builders emit SVG strings in JS), and the
        # visual-concept parcel boundary editor.
        index_source = read_frontend_text()
        shell_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for library in ('font-awesome', 'fontawesome', 'material-icons', 'bootstrap-icons', 'lucide'):
            self.assertNotIn(library, index_source.lower(), f'{library} must not be used')
        self.assertEqual(shell_source.count('<svg'), 1, 'the shell may inline only the favicon SVG')
        self.assertEqual(index_source.count('<svg'), 6,
            'allowed SVG: favicon + map overlay + the three admin dashboard chart builders + parcel boundary editor')
        self.assertIn('id="mapPolygonOverlay"', index_source)

        # Missing logos fall back to a text monogram rather than a building glyph.
        self.assertIn('function teamMonogramHtml(name, size)', index_source)

        # The emoji-to-SVG converter is gone: it created icons the next line deleted.
        slide_source = read_module_source('slide_engine.py')
        self.assertNotIn('_replace_emojis_with_svg', slide_source)
        self.assertNotIn('import emoji_icons', slide_source)
        self.assertIn('def _strip_presentation_icons(html)', slide_source)

    def test_team_library_is_a_flat_list_of_entities(self):
        """Categories were removed: each entity already states what it does in its role field, so
        the extra layer only added a step and a way to fail."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        listed = client.get('/api/team-entities', headers=headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertEqual(listed.get_json()['entities'], [])
        self.assertNotIn('categories', listed.get_json())

        for removed in ('TEAM_SINGLETON_CATEGORIES', 'TEAM_CATEGORY_LABELS', 'TEAM_CATEGORY_FIELDS',
                        'get_team_categories', 'create_team_category', 'team_category_is_full'):
            self.assertFalse(hasattr(db, removed), f'{removed} must no longer exist')
        # The category endpoints are gone with them.
        self.assertEqual(client.post('/api/team-categories', headers=headers,
                                     json={'label': 'x'}).status_code, 404)

        created = client.post('/api/team-entities', headers=headers, json={
            'name': 'Landloom', 'experienceYears': '15',
            'role': 'مطور المشروع', 'brief': 'مطور عقاري سعودي',
            'notableProjects': 'برج الأمير\nمجمع الواحة'})
        self.assertEqual(created.status_code, 201, created.get_json())
        entity = created.get_json()['entity']
        self.assertEqual(entity['role'], 'مطور المشروع')
        self.assertEqual(entity['experienceYears'], '15')
        self.assertNotIn('categoryId', entity)

        # A name is required; a dangling logo id is refused rather than stored.
        self.assertEqual(client.post('/api/team-entities', headers=headers,
                                     json={'name': '  '}).status_code, 400)
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'name': 'شعار مفقود', 'logoFileId': 'nope'}).status_code, 400)

        # No cap on how many entities exist.
        for name in ('مكتب هندسي', 'مقاول', 'استشاري'):
            self.assertEqual(client.post('/api/team-entities', headers=headers,
                                         json={'name': name}).status_code, 201)
        self.assertEqual(len(client.get('/api/team-entities', headers=headers).get_json()['entities']), 4)

        # Tenant-scoped.
        self.assertEqual(client.get('/api/team-entities', headers=self._headers(self.token_b)).get_json()['entities'], [])

        updated = client.put('/api/team-entities/' + entity['id'], headers=headers,
                             json={'name': 'Landloom', 'role': 'المطور والمشغل'})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()['entity']['role'], 'المطور والمشغل')

        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 200)
        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 404)

        # No category UI survives in the settings page.
        index_source = read_frontend_text()
        for gone in ('teamCategoryLabel', 'teamEntityCategory', 'tenantTeamCategories',
                     'submitTeamCategory', 'teamEntityBlocked', 'team-categories'):
            self.assertNotIn(gone, index_source, f'{gone} should have been removed')

    def test_openrouter_empty_body_is_reported_not_parsed(self):
        """An empty or unparseable response body must not leak a raw JSONDecodeError to the user.
        The previous flow exposed 'Expecting value: line 1 column 1 (char 0)' as the providerError."""
        from unittest.mock import patch, Mock

        def make_response(status, text, json_side_effect=None):
            r = Mock()
            r.status_code = status
            r.text = text
            if json_side_effect:
                r.json.side_effect = json_side_effect
            else:
                r.json.return_value = {'error': {'message': 'some provider error'}}
            return r

        empty = make_response(200, '')
        bad_json = make_response(200, 'not json', json_side_effect=ValueError('Expecting value: line 1 column 1 (char 0)'))
        http_error = make_response(503, '{"error":{"message":"Service Unavailable"}}')

        with patch('app.requests.post', side_effect=[empty, bad_json, http_error]):
            for response, expected in ((empty, '200'), (bad_json, '200'), (http_error, '503')):
                result = self.application_module.call_openrouter_chat(
                    'system', 'user', max_tokens=100, timeout=5)
                self.assertIn('error', result, f'status {response.status_code}')
                self.assertNotIn('Expecting value', result['error'].get('message', ''),
                                 f'raw JSONDecodeError leaked for status {response.status_code}')
                self.assertNotIn('line 1 column 1', result['error'].get('message', ''))
                self.assertIn(expected, result['error'].get('message', ''),
                              f'status code not in message for status {response.status_code}')

    def test_openrouter_chat_attaches_visual_references_as_multimodal_content(self):
        module = self.application_module
        response = Mock()
        response.status_code = 200
        response.text = '{"choices":[{"message":{"content":"ok"}}]}'
        response.json.return_value = {'choices': [{'message': {'content': 'ok'}}]}
        with patch('app.requests.post', return_value=response) as post:
            result = module.call_openrouter_chat(
                'system', 'instructions', model='google/gemini-3.8-flash',
                reasoning_effort='high', image_references=['data:image/png;base64,AAAA'])
        self.assertIn('choices', result)
        request_payload = post.call_args.kwargs['json']
        user_content = request_payload['messages'][1]['content']
        self.assertEqual(user_content[0], {'type': 'text', 'text': 'instructions'})
        self.assertEqual(user_content[1]['type'], 'image_url')
        self.assertEqual(user_content[1]['image_url']['url'], 'data:image/png;base64,AAAA')
        self.assertEqual(request_payload['reasoning_effort'], 'high')

    def test_app_never_answers_502(self):
        """The hosting edge fabricates 502s of its own for large bodies, so an app that also answers
        502 makes "the proxy broke" and "the AI failed" impossible to tell apart.
        Exception: DESIGNER_INVALID_PLAN uses 502 deliberately — the planner returned no valid
        actions, which is an upstream AI failure, not a proxy failure. The error_code field
        distinguishes it from a proxy-fabricated 502."""
        app_source = read_module_source('app.py')
        # The only allowed 502 is DESIGNER_INVALID_PLAN (upstream AI returned no valid plan).
        # Strip that one occurrence before checking the rest of the file.
        app_without_designer_502 = app_source.replace(
            "'error_code': 'DESIGNER_INVALID_PLAN'}), 502", ''
        )
        self.assertNotIn('), 502', app_without_designer_502,
                         '502 must be left to the proxy; use 503 for an upstream dependency')
        # The handled cases keep saying what happened, just under their own status.
        self.assertIn("'failureReason': 'truncated',", app_source)
        self.assertIn("'failureReason': 'invalid_json',", app_source)
        self.assertIn('), 503', app_source)

        # The land-analysis reason must survive on screen, not only in a toast.
        index_source = read_frontend_text()
        self.assertIn('function showLandAnalysisFailure(reason, providerError)', index_source)
        self.assertIn('showLandAnalysisFailure(reason, res.providerError);', index_source)
        self.assertIn('clearLandAnalysisFailure();', index_source)
        self.assertIn('لم يتم تحديث أي حقل — التفصيل أسفل خانة الملفات', index_source)

    def test_shell_is_compressed_and_revalidates_instead_of_redownloading(self):
        """The SPA shell is ~740KB and was sent with no-store and no compression, so every load
        pulled all of it down again."""
        client = self.app.test_client()
        plain = client.get('/', headers={'Accept': 'text/html'})
        gzipped = client.get('/', headers={'Accept': 'text/html', 'Accept-Encoding': 'gzip'})

        self.assertEqual(gzipped.headers.get('Content-Encoding'), 'gzip')
        self.assertLess(len(gzipped.data), len(plain.data) / 2, 'compression should at least halve it')
        self.assertIn('Accept-Encoding', gzipped.headers.get('Vary', ''))

        # no-store forbids keeping a copy at all; no-cache keeps one and revalidates.
        self.assertEqual(plain.headers.get('Cache-Control'), 'no-cache')
        self.assertNotIn('no-store', plain.headers.get('Cache-Control', ''))
        etag = plain.headers.get('ETag')
        self.assertTrue(etag)
        revalidated = client.get('/', headers={'Accept': 'text/html', 'If-None-Match': etag})
        self.assertEqual(revalidated.status_code, 304)
        self.assertEqual(len(revalidated.data), 0)

        # JSON is compressed too, and a short body is left alone.
        listed = client.get('/api/team-entities', headers={
            **self._headers(self.token_a), 'Accept-Encoding': 'gzip'})
        self.assertEqual(listed.status_code, 200)
        self.assertIsNone(listed.headers.get('Content-Encoding'),
                          'a tiny payload is not worth compressing')

    def test_prebuilt_field_sync_writes_only_on_change(self):
        """It ran one UPDATE per prebuilt field on every /api/fields call — 39 writes and a commit
        per project-form load, none of which changed anything in the normal case."""
        source = read_module_source('db.py')
        self.assertIn('if unchanged:', source)
        self.assertIn('if dirty:', source)

        client = self.app.test_client()
        first = client.get('/api/fields', headers=self._headers(self.token_a))
        self.assertEqual(first.status_code, 200)

        # Second identical call must not write anything.
        writes = []
        real_execute = db.get_db

        with self.app.app_context():
            conn = db.get_db()
            original = conn.execute

            def spy(sql, *args):
                if not sql.lstrip().upper().startswith('SELECT'):
                    writes.append(sql.split()[0].upper())
                return original(sql, *args)

            conn.execute = spy
            try:
                db.ensure_tenant_prebuilt_fields_active(self.tenant_a)
            finally:
                conn.execute = original
        self.assertEqual(writes, [], f'steady-state sync must not write, got {writes}')
