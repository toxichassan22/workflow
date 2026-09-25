class MeetingRequirementsTestsPart05(MeetingRequirementsTests):

    def test_site_analysis_prefers_google_link_over_stale_coordinates(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'extract_coords_from_maps_link', return_value={'lat': 25.123456, 'lng': 47.654321}), \
                patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={'success': True, 'landmarks': []}), \
                patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[]), \
                patch.object(self.application_module.maps_service, 'discover_nearby_roads', return_value=[]), \
                patch.object(self.application_module.maps_service, '_fetch_osm_polygon', return_value=None), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': '24.000000',
                    'location_lng': '46.000000',
                    'location_address': 'https://www.google.com/maps/@25.123456,47.654321,17z'
                },
                'generateMaps': False,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload['fields']['location_lat'], 25.123456)
        self.assertEqual(payload['fields']['location_lng'], 47.654321)
        self.assertTrue(payload['mapsDeferred'])
        generate_maps.assert_not_called()

    def test_saved_map_assets_hydrate_by_draft_id(self):
        map_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='.png', delete=False)
        map_path = map_file.name
        self.addCleanup(lambda: os.path.exists(map_path) and os.unlink(map_path))
        map_file.write(b'png')
        map_file.close()
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a,
                'overview',
                map_path,
                '##MAP_OVERVIEW##',
                presentation_id='draft_draft-map',
                metadata={
                    'lat': 24.1,
                    'lng': 46.2,
                    'zoom': 17,
                    'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
                }
            )
            hydrated = self.application_module._merge_persisted_map_assets(
                {'project_name': 'Saved'}, self.tenant_a, draft_id='draft-map'
            )
        self.assertEqual(os.path.basename(hydrated['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##']), os.path.basename(map_path))
        self.assertEqual(hydrated['tenantCreativeImages']['map_lat'], 24.1)
        self.assertEqual(hydrated['tenantCreativeImages']['map_lng'], 46.2)

    def test_slide_requests_merge_persisted_maps_into_generation_images(self):
        map_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='.png', delete=False)
        map_path = map_file.name
        self.addCleanup(lambda: os.path.exists(map_path) and os.unlink(map_path))
        map_file.write(b'png')
        map_file.close()
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a,
                'overview',
                map_path,
                '##MAP_OVERVIEW##',
                presentation_id='pres-map-hydration',
                metadata={
                    'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
                }
            )
            project, images = self.application_module._hydrate_map_assets_for_request(
                {'project_name': 'Saved'}, {}, self.tenant_a,
                presentation_id='pres-map-hydration'
            )

        self.assertEqual(
            images['map_placeholders']['##MAP_OVERVIEW##'],
            project['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'],
        )
        self.assertTrue(images['map_placeholders']['##MAP_OVERVIEW##'].endswith(os.path.basename(map_path)))

    def test_slide_requests_prefer_latest_edited_map_over_stale_browser_assets(self):
        old_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_old.png', delete=False)
        old_path = old_file.name
        old_file.write(b'old-browser-map')
        old_file.close()
        edited_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_edited.png', delete=False)
        edited_path = edited_file.name
        edited_file.write(b'latest-edited-map')
        edited_file.close()
        editable_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_editable.png', delete=False)
        editable_path = editable_file.name
        editable_file.write(b'clean-sidecar')
        editable_file.close()
        for path in (old_path, edited_path, editable_path):
            self.addCleanup(lambda p=path: os.path.exists(p) and os.unlink(p))

        metadata = {
            'lat': 24.0,
            'lng': 46.0,
            'zoom': 18,
            'center_lat': 24.01,
            'center_lng': 46.01,
            'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
            'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
        }
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'overview', edited_path, '##MAP_OVERVIEW##',
                             presentation_id='pres-edited-map', metadata=metadata)
            db.add_map_image(self.tenant_a, 'overview_editable', editable_path, '##MAP_OVERVIEW_EDITABLE##',
                             presentation_id='pres-edited-map', metadata=metadata)
            project, images = self.application_module._hydrate_map_assets_for_request(
                {
                    'tenantCreativeImages': {
                        'map_placeholders': {
                            '##MAP_OVERVIEW##': '/old-saved-map.png',
                            '##MAP_OVERVIEW_EDITABLE##': '/old-sidecar.png',
                        },
                        'map_zooms': {'overview': 12},
                        'map_centers': {'overview': {'lat': 25.0, 'lng': 47.0}},
                    }
                },
                {
                    'map_placeholders': {
                        '##MAP_OVERVIEW##': '/old-browser-map.png',
                        '##MAP_OVERVIEW_EDITABLE##': '/old-browser-sidecar.png',
                    },
                    'map_zooms': {'overview': 11},
                    'map_centers': {'overview': {'lat': 26.0, 'lng': 48.0}},
                },
                self.tenant_a,
                presentation_id='pres-edited-map',
            )

        self.assertTrue(images['map_placeholders']['##MAP_OVERVIEW##'].endswith(os.path.basename(edited_path)))
        self.assertTrue(images['map_placeholders']['##MAP_OVERVIEW_EDITABLE##'].endswith(os.path.basename(edited_path)))
        self.assertEqual(images['map_zooms']['overview'], 18)
        self.assertEqual(images['map_centers']['overview'], {'lat': 24.01, 'lng': 46.01})
        self.assertEqual(project['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'],
                         images['map_placeholders']['##MAP_OVERVIEW##'])

    def test_map_hydration_keeps_clean_sidecar_out_of_generation_alias(self):
        final_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_final.png', delete=False)
        final_path = final_file.name
        final_file.write(b'marked-map')
        final_file.close()
        editable_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_clean.png', delete=False)
        editable_path = editable_file.name
        editable_file.write(b'clean-sidecar')
        editable_file.close()
        for path in (final_path, editable_path):
            self.addCleanup(lambda p=path: os.path.exists(p) and os.unlink(p))

        metadata = {
            'lat': 24.0,
            'lng': 46.0,
            'zoom': 12,
            'center_lat': 24.0,
            'center_lng': 46.0,
            'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
            'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
        }
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'catchment', final_path, '##MAP_CATCHMENT##',
                             presentation_id='pres-clean-sidecar', metadata=metadata)
            db.add_map_image(self.tenant_a, 'catchment_editable', editable_path,
                             '##MAP_CATCHMENT_EDITABLE##', presentation_id='pres-clean-sidecar',
                             metadata=metadata)
            project, images = self.application_module._hydrate_map_assets_for_request(
                {'tenantCreativeImages': {}},
                {
                    'map_placeholders': {
                        '##MAP_CATCHMENT##': '/uploads/maps/current-marked.png',
                        # This is the generation-only alias that the browser may
                        # send back after a presentation chat turn.
                        '##MAP_CATCHMENT_EDITABLE##': '/uploads/maps/current-marked.png',
                    },
                    'maps_persisted': True,
                    'map_approvals': {'catchment': True},
                },
                self.tenant_a,
                presentation_id='pres-clean-sidecar',
            )

        project_placeholders = project['tenantCreativeImages']['map_placeholders']
        self.assertEqual(project_placeholders['##MAP_CATCHMENT##'], '/uploads/maps/current-marked.png')
        self.assertTrue(project_placeholders['##MAP_CATCHMENT_EDITABLE##'].endswith(os.path.basename(editable_path)))
        self.assertEqual(images['map_placeholders']['##MAP_CATCHMENT##'], '/uploads/maps/current-marked.png')
        self.assertEqual(images['map_placeholders']['##MAP_CATCHMENT_EDITABLE##'], '/uploads/maps/current-marked.png')

    def test_approved_request_map_beats_older_google_row(self):
        google_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_google.png', delete=False)
        google_path = google_file.name
        google_file.write(b'google-map')
        google_file.close()
        edited_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_approved.png', delete=False)
        edited_path = edited_file.name
        edited_file.write(b'approved-edited-map')
        edited_file.close()
        for path in (google_path, edited_path):
            self.addCleanup(lambda p=path: os.path.exists(p) and os.unlink(p))

        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, 'overview', google_path, '##MAP_OVERVIEW##',
                presentation_id='pres-approved-map', metadata={}
            )
            project, images = self.application_module._hydrate_map_assets_for_request(
                {'project_name': 'Saved'},
                {
                    'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/approved.png'},
                    'maps_persisted': True,
                    'map_approvals': {'overview': True},
                },
                self.tenant_a,
                presentation_id='pres-approved-map',
            )

        self.assertEqual(images['map_placeholders']['##MAP_OVERVIEW##'], '/uploads/maps/approved.png')
        self.assertEqual(project['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'],
                         '/uploads/maps/approved.png')

    def test_duplicate_map_rows_keep_the_newest_valid_row(self):
        old_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_old_google.png', delete=False)
        old_path = old_file.name
        old_file.write(b'old-google-map')
        old_file.close()
        new_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='_new_edited.png', delete=False)
        new_path = new_file.name
        new_file.write(b'new-edited-map')
        new_file.close()
        for path in (old_path, new_path):
            self.addCleanup(lambda p=path: os.path.exists(p) and os.unlink(p))

        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'overview', old_path, '##MAP_OVERVIEW##',
                             presentation_id='pres-duplicate-map', metadata={})
            db.add_map_image(self.tenant_a, 'overview', new_path, '##MAP_OVERVIEW##',
                             presentation_id='pres-duplicate-map', metadata={})
            _project, images = self.application_module._hydrate_map_assets_for_request(
                {'project_name': 'Saved'}, {}, self.tenant_a,
                presentation_id='pres-duplicate-map'
            )

        self.assertTrue(images['map_placeholders']['##MAP_OVERVIEW##'].endswith(os.path.basename(new_path)))

    def test_saved_legacy_map_file_is_not_wiped_by_renderer_version_change(self):
        map_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='.png', delete=False)
        map_path = map_file.name
        self.addCleanup(lambda: os.path.exists(map_path) and os.unlink(map_path))
        map_file.write(b'png')
        map_file.close()
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a,
                'overview',
                map_path,
                '##MAP_OVERVIEW##',
                presentation_id='pres-legacy-map',
                metadata={'map_highlight_version': 'old', 'map_label_version': 'old'},
            )
            hydrated = self.application_module._merge_persisted_map_assets(
                {'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/old-saved-map.png'}}},
                self.tenant_a,
                presentation_id='pres-legacy-map',
            )

        self.assertTrue(hydrated['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'].endswith(os.path.basename(map_path)))

    def test_bulk_map_generation_is_rejected_before_provider_calls(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/generate-map-images', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'draftId': 'maps-draft',
                    'location_analysis_approved': True,
                }
            })

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'INDIVIDUAL_MAP_GENERATION_REQUIRED')
        generate_maps.assert_not_called()

    def test_single_map_regeneration_bypasses_cached_assets(self):
        client = self.app.test_client()
        # The map gates read approval from the stored draft, never the payload.
        with self.app.app_context():
            db.save_project_draft(self.tenant_a, 'owner',
                                  {'project_name': 'One map', 'location_lat': 24.0,
                                   'location_lng': 46.0, 'location_analysis_approved': True,
                                   'tenantCreativeImages': {'map_approvals': {'overview': True}}},
                                  {'basic': 'draft'}, 'draft', draft_id='one-map')
        with patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={
            'placeholders': {'##MAP_ACCESS##': '/uploads/maps/access.png'},
            'landmarks': [],
            'landmarks_matrix': [],
            'zooms': {'access': 16},
        }) as generate_maps:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'one-map',
                                'location_analysis_approved': True},
                'mapType': 'access',
                'overviewApproved': True,
                'regenSeed': 17,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        generated_project = generate_maps.call_args.args[0]
        self.assertEqual(generated_project['enabled_maps'], ['access'])
        self.assertTrue(generated_project['refresh_maps'])
        self.assertEqual(generated_project['regen_seed'], 17)
        self.assertFalse(generate_maps.call_args.kwargs.get('force'))

    def test_location_analysis_approval_gates_individual_map_generation(self):
        client = self.app.test_client()
        base = {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'approval-map'}
        # The gates read approval from the stored draft; the payload cannot mint it.
        with self.app.app_context():
            db.save_project_draft(self.tenant_a, 'owner',
                                  {'project_name': 'Approval map', 'location_lat': 24.0,
                                   'location_lng': 46.0},
                                  {'basic': 'draft'}, 'draft', draft_id='approval-map')
        response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
            'projectData': base, 'mapType': 'overview'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'LOCATION_ANALYSIS_NOT_APPROVED')
        with self.app.app_context():
            db.save_project_draft(self.tenant_a, 'owner',
                                  {'project_name': 'Approval map', 'location_lat': 24.0,
                                   'location_lng': 46.0, 'location_analysis_approved': True},
                                  {'basic': 'draft'}, 'draft', draft_id='approval-map')
        response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
            'projectData': {**base, 'location_analysis_approved': True}, 'mapType': 'access'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'OVERVIEW_MAP_NOT_APPROVED')
        with self.app.app_context():
            db.save_project_draft(self.tenant_a, 'owner',
                                  {'project_name': 'Approval map', 'location_lat': 24.0,
                                   'location_lng': 46.0, 'location_analysis_approved': True,
                                   'tenantCreativeImages': {'map_approvals': {'overview': True}}},
                                  {'basic': 'draft'}, 'draft', draft_id='approval-map')
        with patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {**base, 'location_analysis_approved': True},
                'mapType': 'overview',
                'mapApproved': True,
            })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'MAP_ALREADY_APPROVED')
        delete_images.assert_not_called()
        self.assertFalse(self.application_module._location_workflow_complete({'draft_data': {}}))
        self.assertTrue(self.application_module._location_workflow_complete({'draft_data': {
            'location_analysis_approved': True,
            'tenantCreativeImages': {'map_approvals': {
                'overview': True, 'access': True, 'catchment': True, 'landmarks': True}}
        }}))
        rows = [{'name': f'معلم {index}', 'show_on_map': index in (2, 4)} for index in range(1, 10)]
        self.assertEqual([row['name'] for row in self.application_module.maps_service.select_map_landmark_rows(rows)],
                         ['معلم 2', 'معلم 4'])
        self.assertEqual(len(self.application_module.maps_service.select_map_landmark_rows(
            [{'name': f'معلم {index}'} for index in range(1, 10)])), 7)
        source = read_frontend_text()
        analyze_body = source.split('async function analyzeTenantSiteOnce()', 1)[1].split('const MAP_PREVIEW_VIEW_DEFS', 1)[0]
        self.assertIn('generateMaps: false', analyze_body)
        self.assertNotIn('await previewProjectMap(', analyze_body)
        self.assertIn('location_analysis_approved', source)
        self.assertIn('function toggleLocationAnalysisApproval()', source)
        self.assertIn('function startManualRoadDrawing(name)', source)
        self.assertIn('function startLandmarkPlacement(key, tr)', source)
        self.assertIn('main_roads_data', source)
        self.assertIn("overviewApproved: !!approvals.overview", source)
        self.assertIn("mapApproved: !!approvals[mapType]", source)
        self.assertIn("if (mapType !== 'overview' && !approvals.overview)", source)
        self.assertIn('اعتماد الخرائط الأربع مطلوب قبل توليد العرض', source)
        self.assertIn("city_landmarks: { nameLabel: 'مَعلم المدينة'", source)
        self.assertNotIn("secondary_roads: { nameLabel:", source)
        self.assertIn('tenantProjectData.location_lat = latValue', source)
        pin_body = source.split('function setTenantMapPointFromClick(event)', 1)[1].split('function updateTenantPolygonControls()', 1)[0]
        self.assertIn('tenantMapDraftPinHistory.push([nextLat, nextLng])', pin_body)
        self.assertNotIn('tenantProjectData.location_lat = nextLat.toFixed(6)', pin_body)
        self.assertNotIn("tenantProjectData.location_polygon = ''", pin_body)
        self.assertIn("return regenerateMapPreview('overview');", source)
        self.assertNotIn("'/api/generate-map-images'", source)
        self.assertIn('({ ...row, name })', source)
        self.assertIn('tenantProjectData.manual_road_paths', source)
        self.assertIn('show_on_map', source)
        app_source = read_module_source('app.py')
        designer_body = app_source.split('def api_designer_chat():', 1)[1].split("@app.route('/api/files'", 1)[0]
        self.assertNotIn('generate_all_map_images(', designer_body)
        self.assertEqual(app_source.count('generate_all_map_images('), 1)
        maps_source = read_module_source('maps_service.py')
        self.assertIn('overview_markers = _build_markers(marker_lat, marker_lng)', maps_source)
        self.assertIn('_draw_catchment_markers(', maps_source)
        self.assertNotIn('marker_lat, marker_lng = map_center_lat, map_center_lng', maps_source)
        access_body = maps_source.split('def _draw_access_roads(', 1)[1].split('def _get_cached_map_images(', 1)[0]
        self.assertNotIn("('main_roads', 'secondary_roads')", access_body)

    def test_map_gallery_respects_approval_stages_and_editable_saved_maps(self):
        source = read_frontend_text()
        self.assertIn('function mapPreviewStoredUrl(view)', source)
        self.assertIn("...(view.editableKeys || [])", source)
        self.assertIn('function mapPreviewIsVisible(view, approvals = tenantCreativeImages?.map_approvals || {})', source)
        self.assertIn("'بانتظار اعتماد خريطة الأرض / المبنى'", source)
        self.assertIn("'بانتظار اعتماد تحليل الموقع'", source)
        self.assertIn("'معتمدة بدون ملف'", source)
        self.assertIn('const approvalButton = generated || mapApproved', source)
        self.assertIn('} else if (mapApproved) {', source)
        gallery_body = source.split('function renderMapPreviewGallery()', 1)[1].split('function withCacheBust', 1)[0]
        self.assertIn('const visible = mapPreviewIsVisible(view, approvals);', gallery_body)
        self.assertIn('visible && url', gallery_body)
        self.assertIn('const overviewGenerated = mapPreviewIsGenerated(overview);', source)
        self.assertIn('const generated = mapPreviewIsGenerated(view);', source)

    def test_overview_map_has_dedicated_generation_and_edit_modes(self):
        index_source = read_frontend_text()
        approval_panel = index_source.split('id="locationAnalysisApprovalPanel"', 1)[1].split('</div>', 1)[0]
        self.assertIn('id="generateOverviewMapButton"', approval_panel)
        self.assertIn('onclick="generateOverviewMap()"', approval_panel)
        workflow_body = index_source.split('function renderLocationWorkflowState()', 1)[1].split('function openLocationTableMap', 1)[0]
        self.assertIn("if (view.mapType === 'overview' && tenantMapPolygonMode)", workflow_body)
        self.assertIn('تراجع عن آخر نقطة', workflow_body)
        self.assertIn('مسح التحديد', workflow_body)
        self.assertIn('اعتماد الحدود', workflow_body)
        self.assertIn("if (view.mapType === 'overview' && tenantMapPinMode)", workflow_body)
        self.assertIn('اعتماد التعيين', workflow_body)
        self.assertIn('function generateOverviewMap()', index_source)
        self.assertIn('function startTenantMapPinMode()', index_source)
        self.assertIn('function undoTenantMapPin()', index_source)
        self.assertIn('function cancelTenantMapPin()', index_source)
        self.assertIn('async function confirmTenantMapPin()', index_source)
        self.assertIn("tenantSelectedMapType === 'overview' && tenantMapPinMode", index_source)
        self.assertIn("editableKeys: ['##MAP_OVERVIEW_EDITABLE##'", index_source)
        self.assertNotIn('function applyTenantPolygonZoom()', index_source)
        maps_source = read_module_source('maps_service.py')
        self.assertIn("'##MAP_OVERVIEW_EDITABLE##'", maps_source)
        self.assertIn('shutil.copyfile(overview_path, editable_path)', maps_source)

    def test_confirmed_map_pin_overrides_the_original_google_link(self):
        service = self.application_module.maps_service
        with patch.object(service, 'extract_coords_from_maps_link', return_value={'lat': 25.0, 'lng': 45.0}):
            lat, lng = service._resolve_map_coordinates({
                'location_address': 'https://www.google.com/maps/@25,45,17z',
                'location_lat': '24.123456',
                'location_lng': '46.654321',
                'location_coordinates_confirmed': True,
            }, self.tenant_a)
            self.assertEqual((lat, lng), (24.123456, 46.654321))
            linked_lat, linked_lng = service._resolve_map_coordinates({
                'location_address': 'https://www.google.com/maps/@25,45,17z',
                'location_lat': '24.123456',
                'location_lng': '46.654321',
                'location_coordinates_confirmed': False,
            }, self.tenant_a)
            self.assertEqual((linked_lat, linked_lng), (25.0, 45.0))

    def test_overview_edits_recompose_without_full_map_generation(self):
        client = self.app.test_client()
        result = {'placeholders': {}, 'zooms': {'overview': 18}, 'centers': {'overview': {'lat': 24.0, 'lng': 46.0}}, 'site_polygon': []}
        with patch.object(self.application_module.maps_service, 'recompose_overview_map', return_value=result) as recompose, \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps, \
                patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'quick-overview',
                                'location_analysis_approved': True, 'location_coordinates_confirmed': True},
                'mapType': 'overview',
                'overlayOnly': True,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        recompose.assert_called_once()
        generate_maps.assert_not_called()
        delete_images.assert_not_called()

        from PIL import Image
        editable_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        editable_path = editable_file.name
        editable_file.close()
        final_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        final_path = final_file.name
        final_file.close()
        self.addCleanup(lambda: os.path.exists(editable_path) and os.unlink(editable_path))
        self.addCleanup(lambda: os.path.exists(final_path) and os.unlink(final_path))
        Image.new('RGB', (1280, 720), '#ddd8cf').save(editable_path)
        metadata = {'lat': 24.0, 'lng': 46.0, 'zoom': 18, 'center_lat': 24.0, 'center_lng': 46.0,
                    'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
                    'highlight_site': True}
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'overview_editable', editable_path, '##MAP_OVERVIEW_EDITABLE##',
                             'draft_quick-compose', metadata)
            with patch.object(self.application_module.maps_service, 'get_static_map') as provider, \
                    patch.object(self.application_module.maps_service, 'geocode_address') as geocode, \
                    patch.object(self.application_module.maps_service, '_unique_map_path', return_value=final_path):
                composed = self.application_module.maps_service.recompose_overview_map({
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'location_coordinates_confirmed': True,
                    'location_polygon': '23.9999,45.9999;23.9999,46.0001;24.0001,46.0001;24.0001,45.9999',
                }, self.tenant_a, draft_id='quick-compose', highlight_site=True)
            provider.assert_not_called()
            geocode.assert_not_called()
        self.assertNotIn('error', composed)
        self.assertEqual(composed['placeholders']['##MAP_OVERVIEW##'], final_path)
        self.assertNotEqual(Path(editable_path).read_bytes(), Path(final_path).read_bytes())

        source = read_frontend_text()
        drawing_start = source.split('async function toggleTenantPolygonMode()', 1)[1].split('function cancelTenantPolygonMode()', 1)[0]
        boundary_confirm = source.split('async function confirmTenantPolygon()', 1)[1].split('async function startTenantMapPinMode()', 1)[0]
        pin_start = source.split('async function startTenantMapPinMode()', 1)[1].split('function undoTenantMapPin()', 1)[0]
        pin_confirm = source.split('async function confirmTenantMapPin()', 1)[1].split('function syncTenantLocationPolygon()', 1)[0]
        quick_update = source.split('async function applyOverviewMapEdits()', 1)[1].split('async function toggleTenantPolygonMode()', 1)[0]
        self.assertNotIn('regenerateMapPreview(', drawing_start)
        self.assertNotIn('regenerateMapPreview(', pin_start)
        self.assertNotIn('regenerateMapPreview(', boundary_confirm)
        self.assertNotIn('regenerateMapPreview(', pin_confirm)
        self.assertIn('await applyOverviewMapEdits()', boundary_confirm)
        self.assertIn('await applyOverviewMapEdits()', pin_confirm)
        self.assertIn('overlayOnly: true', quick_update)
        self.assertNotIn('showLoader(', quick_update)
        self.assertNotIn('ensureEditableOverviewPreview()', drawing_start)
        self.assertNotIn('ensureEditableOverviewPreview()', pin_start)

    def test_access_map_edits_are_scoped_persistent_and_provider_free(self):
        client = self.app.test_client()
        result = {'placeholders': {}, 'zooms': {'access': 16}, 'centers': {'access': {'lat': 24.0, 'lng': 46.0}}, 'access_roads': []}
        with patch.object(self.application_module.maps_service, 'recompose_access_map', return_value=result) as recompose, \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps, \
                patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'quick-access',
                                'location_analysis_approved': False, 'location_coordinates_confirmed': True},
                'mapType': 'access',
                'overlayOnly': True,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        recompose.assert_called_once()
        generate_maps.assert_not_called()
        delete_images.assert_not_called()

        from PIL import Image
        editable_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        editable_path = editable_file.name
        editable_file.close()
        final_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        final_path = final_file.name
        final_file.close()
        self.addCleanup(lambda: os.path.exists(editable_path) and os.unlink(editable_path))
        self.addCleanup(lambda: os.path.exists(final_path) and os.unlink(final_path))
        Image.new('RGB', (1280, 720), '#ddd8cf').save(editable_path)
        metadata = {'lat': 24.0, 'lng': 46.0, 'zoom': 16, 'center_lat': 24.0, 'center_lng': 46.0,
                    'access_roads_version': self.application_module.maps_service.ACCESS_ROADS_RENDER_VERSION,
                    'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION}
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'access_editable', editable_path, '##MAP_ACCESS_EDITABLE##',
                             'draft_quick-access-compose', metadata)
            with patch.object(self.application_module.maps_service, 'get_static_map') as provider, \
                    patch.object(self.application_module.maps_service, '_snap_to_roads') as roads_provider, \
                    patch.object(self.application_module.maps_service, '_google_directions_route') as directions_provider, \
                    patch.object(self.application_module.maps_service, '_unique_map_path', return_value=final_path):
                composed = self.application_module.maps_service.recompose_access_map({
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'main_roads': 'شارع صحيح',
                    'access_roads_data': [{'name': 'شارع صحيح', 'points': [[24.0, 45.9998], [24.0, 46.0002]]}],
                    'access_road_label_positions': {'شارع صحيح': [24.0001, 46.0]},
                    'access_road_label_sizes': {'شارع صحيح': 0.8},
                }, self.tenant_a, draft_id='quick-access-compose')
            provider.assert_not_called()
            roads_provider.assert_not_called()
            directions_provider.assert_not_called()
        self.assertNotIn('error', composed)
        self.assertEqual(composed['placeholders']['##MAP_ACCESS##'], final_path)
        self.assertEqual(composed['access_roads'][0]['name'], 'شارع صحيح')
        self.assertEqual(composed['access_roads'][0]['label_scale'], 0.8)
        self.assertNotEqual(Path(editable_path).read_bytes(), Path(final_path).read_bytes())

        source = read_frontend_text()
        workflow = source.split('function renderLocationWorkflowState()', 1)[1].split('function openLocationTableMap', 1)[0]
        for label in ('إعادة توليد الخريطة', 'اعتماد الخريطة', 'إضافة / تعديل الطرق', 'رسم مسار الطرق'):
            self.assertIn(label, workflow)
        for label in ('اختيار الطريق', 'اعتماد المسارات', 'تراجع', 'إلغاء'):
            self.assertIn(label, source)
        self.assertIn("view.mapType === 'access' && tenantRoadEditMode", workflow)
        self.assertIn("view.mapType === 'access' && tenantRoadDrawingTarget", workflow)
        for function_name in ('startAccessRoadEditMode', 'undoAccessRoadEdits', 'confirmAccessRoadEdits',
                              'cancelAccessRoadEdits', 'selectManualRoadDrawingRoad', 'undoManualRoadDrawing',
                              'applyAccessMapEdits'):
            self.assertIn('function ' + function_name + '(', source)
        path_start = source.split('function startManualRoadDrawing(name)', 1)[1].split('async function finishManualRoadDrawing()', 1)[0]
        path_confirm = source.split('async function finishManualRoadDrawing()', 1)[1].split('function cancelManualRoadDrawing()', 1)[0]
        edit_confirm = source.split('async function confirmAccessRoadEdits()', 1)[1].split('function cancelAccessRoadEdits()', 1)[0]
        self.assertNotIn('regenerateMapPreview(', path_start + path_confirm + edit_confirm)
        self.assertNotIn('showLoader(', path_start + path_confirm + edit_confirm)
        self.assertIn('await applyAccessMapEdits()', path_confirm)
        self.assertIn('await applyAccessMapEdits()', edit_confirm)
        self.assertIn('tenantProjectData.manual_road_paths', path_confirm)
        self.assertIn('tenantProjectData.access_road_label_positions', edit_confirm)
        self.assertIn("editableKeys: ['##MAP_ACCESS_EDITABLE##'", source)
        self.assertIn("'access_roads_data'", source)
        self.assertIn('Array.isArray(data.roads)', source)
        self.assertIn("'access_road_label_positions'", source)
        self.assertIn("'access_road_label_sizes'", source)
        self.assertIn('id="mapLabelOverlay"', source)
        self.assertIn('function startAccessRoadLabelDrag(event, name)', source)
        self.assertIn('function adjustAccessRoadLabelSize(delta)', source)
        self.assertIn('function deleteAccessRoadFromDraft(event, name)', source)
        self.assertIn('map-road-label-delete', source)
        self.assertIn('onpointerdown="startAccessRoadLabelDrag(event,', source)
        self.assertIn('onpointerdown="event.stopPropagation()"', source)
        self.assertIn('>حذف</button>', source)
        self.assertIn('تصغير الاسم', source)
        self.assertIn('تكبير الاسم', source)
        self.assertIn('tenantProjectData.main_roads = hidden.value;', source)
        self.assertIn('const allowedRoadKeys = new Set(rows.map(row => accessRoadNameKey(row.name)));', source)
        self.assertIn('.filter(road => allowedRoadKeys.has(accessRoadNameKey(road?.name)))', source)
        self.assertIn('function invalidateAccessMapApproval()', source)

        maps_source = read_module_source('maps_service.py')
        self.assertIn('def recompose_access_map(', maps_source)
        self.assertIn('allow_discovery=False', maps_source)
        self.assertIn("(project_data or {}).get('access_roads_data')", maps_source)
        self.assertIn("(project_data or {}).get('access_road_label_positions')", maps_source)
        self.assertIn("(project_data or {}).get('access_road_label_sizes')", maps_source)
        approved = self.application_module.maps_service._approved_manual_road_paths([
            {'name': 'شارع صحيح', 'points': [[24.0, 46.0], [24.1, 46.1]]},
            {'name': 'شارع غير موجود', 'points': [[24.0, 46.0], [24.1, 46.1]]},
        ], ['شارع صحيح'])
        self.assertEqual([name for _, name in approved], ['شارع صحيح'])

    def test_catchment_map_selection_labels_and_editing_are_scoped(self):
        service = self.application_module.maps_service
        rows = [{'name': f'مكان {index}', 'show_on_map': index == 5} for index in range(1, 10)]
        self.assertEqual([row['name'] for row in service.select_map_landmark_rows(rows)], ['مكان 5'])
        self.assertEqual(len(service.select_map_landmark_rows([
            {'name': f'مكان {index}'} for index in range(1, 10)
        ])), 7)

        client = self.app.test_client()
        result = {'placeholders': {}, 'zooms': {'catchment': 12}, 'centers': {'catchment': {'lat': 24.0, 'lng': 46.0}}, 'catchment_landmarks': []}
        with patch.object(service, 'recompose_catchment_map', return_value=result) as recompose, \
                patch.object(service, 'generate_all_map_images') as generate_maps, \
                patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'quick-catchment'},
                'mapType': 'catchment',
                'overlayOnly': True,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        recompose.assert_called_once()
        generate_maps.assert_not_called()
        delete_images.assert_not_called()

        from PIL import Image
        editable_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        editable_path = editable_file.name
        editable_file.close()
        final_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        final_path = final_file.name
        final_file.close()
        self.addCleanup(lambda: os.path.exists(editable_path) and os.unlink(editable_path))
        self.addCleanup(lambda: os.path.exists(final_path) and os.unlink(final_path))
        Image.new('RGB', (1280, 720), '#ddd8cf').save(editable_path)
        metadata = {'lat': 24.0, 'lng': 46.0, 'zoom': 12, 'center_lat': 24.0, 'center_lng': 46.0,
                    'map_highlight_version': service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': service.MAP_LABEL_RENDER_VERSION}
        landmarks = [
            {'name': 'مكان أول', 'lat': 24.001, 'lng': 46.001},
            {'name': 'مكان ثان', 'lat': 24.0011, 'lng': 46.0011},
            {'name': 'مكان ثالث', 'lat': 24.0012, 'lng': 46.0012},
        ]
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'catchment_editable', editable_path, '##MAP_CATCHMENT_EDITABLE##',
                             'draft_quick-catchment-compose', metadata)
            with patch.object(service, 'get_static_map') as provider, \
                    patch.object(service, '_unique_map_path', return_value=final_path):
                composed = service.recompose_catchment_map({
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'catchment_map_landmarks': landmarks,
                    'catchment_label_positions': {'مكان أول': [24.002, 46.002]},
                }, self.tenant_a, draft_id='quick-catchment-compose')
            provider.assert_not_called()
        self.assertNotIn('error', composed)
        self.assertEqual(len(composed['catchment_landmarks']), 3)
        self.assertEqual(len({tuple(item['label_point']) for item in composed['catchment_landmarks']}), 3)
        self.assertNotEqual(Path(editable_path).read_bytes(), Path(final_path).read_bytes())

        source = read_frontend_text()
        workflow = source.split('function renderLocationWorkflowState()', 1)[1].split('function openLocationTableMap', 1)[0]
        self.assertIn("view.mapType === 'catchment' && tenantCatchmentEditMode", workflow)
        self.assertIn("view.mapType === 'catchment' && generated", workflow)
        self.assertIn('إعادة توليد الخريطة', workflow)
        self.assertIn('اعتماد الخريطة', workflow)
        self.assertIn('>تعديل</button>', workflow)
        for function_name in ('startCatchmentEditMode', 'startCatchmentLabelDrag', 'undoCatchmentEdits',
                              'confirmCatchmentEdits', 'cancelCatchmentEdits', 'applyCatchmentMapEdits'):
            self.assertIn('function ' + function_name + '(', source)
        confirm_body = source.split('async function confirmCatchmentEdits()', 1)[1].split('function cancelCatchmentEdits()', 1)[0]
        self.assertNotIn('regenerateMapPreview(', confirm_body)
        self.assertNotIn('showLoader(', confirm_body)
        self.assertIn('await applyCatchmentMapEdits()', confirm_body)
        self.assertIn("editableKeys: ['##MAP_CATCHMENT_EDITABLE##'", source)
        self.assertIn("'catchment_label_positions'", source)
        self.assertIn("'catchment_map_landmarks'", source)
        self.assertIn('map-place-label', source)
        self.assertIn('map-place-marker', source)
        self.assertIn('function startCatchmentMarkerDrag(event, name)', source)
        self.assertIn('tenantCatchmentEditDraft.landmarks', source)
        self.assertIn('tenantProjectData.city_landmarks_data =', confirm_body)

        maps_source = read_module_source('maps_service.py')
        self.assertIn('def _draw_catchment_markers(', maps_source)
        self.assertIn('def recompose_catchment_map(', maps_source)
        self.assertIn("project_data.get('catchment_label_positions')", maps_source)
        self.assertIn('preferred_point=', maps_source)

    def test_landmarks_map_editing_preserves_existing_selection_logic(self):
        service = self.application_module.maps_service
        rows = [{'name': f'معلم {index}', 'show_on_map': index in (3, 7)} for index in range(1, 10)]
        self.assertEqual([row['name'] for row in service.select_map_landmark_rows(rows)], ['معلم 3', 'معلم 7'])
        self.assertEqual(len(service.select_map_landmark_rows([{'name': f'معلم {index}'} for index in range(1, 10)])), 7)

        client = self.app.test_client()
        # The map gates read approval from the stored draft, never the payload.
        with self.app.app_context():
            db.save_project_draft(
                self.tenant_a, 'owner', {
                    'project_name': 'Quick landmarks',
                    'location_lat': 24.0, 'location_lng': 46.0,
                    'location_analysis_approved': True,
                    'tenantCreativeImages': {'map_approvals': {'overview': True}},
                }, {'basic': 'approved'}, 'draft', draft_id='quick-landmarks')
        result = {'placeholders': {}, 'zooms': {'landmarks': 14}, 'centers': {'landmarks': {'lat': 24.0, 'lng': 46.0}}, 'landmark_map_items': []}
        with patch.object(service, 'recompose_landmarks_map', return_value=result) as recompose, \
                patch.object(service, 'generate_all_map_images') as generate_maps, \
                patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'quick-landmarks'},
                'mapType': 'landmarks',
                'overlayOnly': True,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        recompose.assert_called_once()
        generate_maps.assert_not_called()
        delete_images.assert_not_called()

        generated_result = {
            'placeholders': {}, 'zooms': {'landmarks': 14},
            'centers': {'landmarks': {'lat': 24.0, 'lng': 46.0}},
            'landmark_map_items': [{'name': 'محدد', 'lat': 24.01, 'lng': 46.01, 'show_on_map': True}],
        }
        with patch.object(service, 'generate_all_map_images', return_value=generated_result) as generate_maps, \
                patch.object(self.application_module.db, 'delete_map_images') as delete_images:
            regenerated = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'quick-landmarks',
                    'location_analysis_approved': True,
                    'nearby_landmarks_data': [
                        {'name': 'محدد', 'lat': 24.01, 'lng': 46.01, 'show_on_map': True},
                        {'name': 'غير محدد', 'lat': 24.02, 'lng': 46.02, 'show_on_map': False},
                    ],
                },
                'mapType': 'landmarks', 'overviewApproved': True, 'regenSeed': 123,
            })
        self.assertEqual(regenerated.status_code, 200, regenerated.get_json())
        generate_maps.assert_called_once()
        sent_project = generate_maps.call_args.args[0]
        self.assertEqual(sent_project['enabled_maps'], ['landmarks'])
        self.assertTrue(sent_project['refresh_maps'])
        self.assertTrue(sent_project['nearby_landmarks_data'][0]['show_on_map'])
        self.assertGreaterEqual(delete_images.call_count, 6)

        from PIL import Image
        editable_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        editable_path = editable_file.name
        editable_file.close()
        final_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        final_path = final_file.name
        final_file.close()
        self.addCleanup(lambda: os.path.exists(editable_path) and os.unlink(editable_path))
        self.addCleanup(lambda: os.path.exists(final_path) and os.unlink(final_path))
        Image.new('RGB', (1280, 720), '#ddd8cf').save(editable_path)
        metadata = {'lat': 24.0, 'lng': 46.0, 'zoom': 14, 'center_lat': 24.0, 'center_lng': 46.0,
                    'map_highlight_version': service.MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': service.MAP_LABEL_RENDER_VERSION}
        with self.app.app_context():
            db.add_map_image(self.tenant_a, 'landmarks_editable', editable_path, '##MAP_LANDMARKS_EDITABLE##',
                             'draft_quick-landmarks-compose', metadata)
            with patch.object(service, 'get_static_map') as provider, \
                    patch.object(service, '_unique_map_path', return_value=final_path):
                composed = service.recompose_landmarks_map({
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'landmark_map_items': [
                        {'name': 'معلم أول', 'lat': 24.001, 'lng': 46.001},
                        {'name': 'معلم ثان', 'lat': 24.002, 'lng': 46.002},
                    ],
                    'landmark_label_positions': {'معلم أول': [24.0015, 46.0015]},
                }, self.tenant_a, draft_id='quick-landmarks-compose')
            provider.assert_not_called()
        self.assertNotIn('error', composed)
        self.assertEqual(len(composed['landmark_map_items']), 2)
        self.assertNotEqual(Path(editable_path).read_bytes(), Path(final_path).read_bytes())

        source = read_frontend_text()
        workflow = source.split('function renderLocationWorkflowState()', 1)[1].split('function openLocationTableMap', 1)[0]
        self.assertIn("view.mapType === 'landmarks' && tenantLandmarksEditMode", workflow)
        self.assertIn("view.mapType === 'landmarks' && generated", workflow)
        self.assertIn('>تعديل</button>', workflow)
        for function_name in ('startLandmarksEditMode', 'startLandmarksLabelDrag', 'startLandmarksMarkerDrag',
                              'undoLandmarksEdits', 'confirmLandmarksEdits', 'cancelLandmarksEdits',
                              'applyLandmarksMapEdits'):
            self.assertIn('function ' + function_name + '(', source)
        confirm_body = source.split('async function confirmLandmarksEdits()', 1)[1].split('function cancelLandmarksEdits()', 1)[0]
        self.assertNotIn('regenerateMapPreview(', confirm_body)
        self.assertNotIn('showLoader(', confirm_body)
        self.assertIn('await applyLandmarksMapEdits()', confirm_body)
        self.assertIn('tenantProjectData.nearby_landmarks_data =', confirm_body)
        self.assertIn('refreshLocationTables()', confirm_body)
        slim_body = source.split('function slimMapProjectData(data)', 1)[1].split('return slim;', 1)[0]
        self.assertIn("'show_on_map'", slim_body)
        self.assertIn("'selected'", slim_body)
        self.assertIn("editableKeys: ['##MAP_LANDMARKS_EDITABLE##'", source)
        self.assertIn("'landmark_label_positions'", source)
        self.assertIn("'landmark_map_items'", source)
        self.assertIn('function isUsableMapCoordinate(value, latitude)', source)
        self.assertIn('function mergeResolvedMapLandmark(row, resolved)', source)
        self.assertIn('mergeResolvedMapLandmark(item, storedByName.get', source)

        maps_source = read_module_source('maps_service.py')
        self.assertIn('def recompose_landmarks_map(', maps_source)
        self.assertIn("project_data.get('landmark_label_positions')", maps_source)

    def test_location_tables_and_controls_are_scoped_to_their_maps(self):
        source = read_frontend_text()
        self.assertNotIn('lt-location-input', source)
        self.assertNotIn('location_url', source)
        self.assertNotIn('<th>رابط الموقع</th>', source)
        self.assertIn("selectTd.className = 'lt-map-toggle';", source)
        self.assertIn('.location-table .lt-map-select {', source)
        self.assertIn('width: 17px;', source)
        self.assertIn("actionGroup.className = 'lt-action-group';", source)
        self.assertIn("delBtn.dataset.sectionLockIgnore = '1';", source)
        self.assertIn("drawBtn.dataset.sectionLockIgnore = '1';", source)
        self.assertIn("placeBtn.dataset.sectionLockIgnore = '1';", source)
        self.assertIn("addBtn.dataset.sectionLockIgnore = '1';", source)
        self.assertIn(".forEach(control => { control.disabled = roadModeLocked || catchmentModeLocked || landmarksModeLocked; });", source)
        self.assertIn('function releaseLocationSectionApproval()', source)
        self.assertIn("applySectionStatuses({ location: 'draft' });", source)
        self.assertIn("document.createElement(cfg.road ? 'textarea' : 'input')", source)
        self.assertIn('resize: vertical;', source)
        self.assertIn("main_roads: { nameLabel: 'الطريق الرئيسي', nameHint: 'مثال: طريق الملك فهد', nameOnly: true, road: true, mapType: 'access' }", source)
        self.assertIn("nearby_landmarks: { nameLabel: 'المَعلم القريب', nameHint: 'مثال: مجمع الراشد', categoryLabel: 'النوع', mapSelectable: true, mapType: 'landmarks' }", source)
        self.assertIn("city_landmarks: { nameLabel: 'مَعلم المدينة', nameHint: 'مثال: الواجهة البحرية', categoryLabel: 'النوع', mapSelectable: true, mapType: 'catchment' }", source)
        workflow_body = source.split('function renderLocationWorkflowState()', 1)[1].split('function openLocationTableMap', 1)[0]
        self.assertIn('MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === tenantSelectedMapType)', workflow_body)
        self.assertIn('onclick="toggleTenantPolygonMode()"', workflow_body)
        self.assertIn('onclick="startTenantMapPinMode()"', workflow_body)
        self.assertNotIn('MAP_PREVIEW_VIEW_DEFS.map(view =>', workflow_body)
        landmark_body = source.split('function startLandmarkPlacement(key, tr)', 1)[1].split('function startManualRoadDrawing', 1)[0]
        self.assertIn('openLocationTableMap(mapType)', landmark_body)
        road_body = source.split('function startManualRoadDrawing(name)', 1)[1].split('function finishManualRoadDrawing', 1)[0]
        self.assertIn("openLocationTableMap('access')", road_body)
        overlay_body = source.split('function renderTenantMapPolygonOverlay()', 1)[1].split('function removeTenantPolygonPoint', 1)[0]
        self.assertIn("const showRoads = tenantSelectedMapType === 'access' &&", overlay_body)

    def test_access_road_names_are_drawn_above_highlights(self):
        source = read_module_source('maps_service.py')
        index_source = read_frontend_text()
        self.assertIn("ACCESS_ROADS_RENDER_VERSION = 'v14-draggable-road-labels'", source)
        self.assertIn("def bundled_arabic_overlay_font_path():", source)
        self.assertIn("def _strip_arabic_diacritics(text):", source)
        self.assertIn("def _arabic_reshaper_without_ligatures():", source)
        self.assertIn("configuration['support_ligatures'] = False", source)
        self.assertIn('from bidi.algorithm import get_display', source)
        self.assertIn("'language': 'ar'", source)
        overlay_font = ROOT / 'fonts' / 'arabic-overlay.bin'
        self.assertGreater(overlay_font.stat().st_size, 10000)
        self.assertEqual(overlay_font.read_bytes()[:4], b'\x00\x01\x00\x00')
        self.assertIn("'feature:road|element:labels|visibility:off'", source)
        self.assertIn('pending_labels.append((route_segment, label_text, coords))', source)
        self.assertIn('labels_overlay = Image.new', source)
        self.assertIn('distance=52', source)
        self.assertIn('candidates = preferred_candidates or visible_candidates', source)
        self.assertIn('ly1 = offset_point[1] - 30', source)
        self.assertLess(
            source.index('draw.line(segment, fill=gold_color, width=9)'),
            source.index('_draw_road_label(labels_draw')
        )
        self.assertIn('function withCacheBust(url)', index_source)
        self.assertIn('payload.refresh_maps = true', index_source)
        self.assertIn('selectMapPreviewView(mapType)', index_source)
        self.assertIn("return regenerateMapPreview(tenantSelectedMapType || 'overview');", index_source)
        self.assertIn('Regenerating a map is an explicit user action.', index_source)
        self.assertIn('await saveProjectAsDraftNow(true)', index_source)

    def test_map_section_has_no_regeneration_controls(self):
        index_source = read_frontend_text()
        self.assertNotIn('data-map-action="regenerate"', index_source)
        self.assertNotIn(
            "closeTenantDropdown(); if(tenantPresentationId){ regeneratePresentationMaps(); } else { ensureProjectAssets({force:true, needImages:false})",
            index_source,
        )
        self.assertNotIn(
            "collectMapStylePanel(); if(tenantPresentationId){ regeneratePresentationMaps(); } else { ensureProjectAssets({force:true, needImages:false})",
            index_source,
        )

    def test_client_entered_land_fields_are_highlighted(self):
        index_source = read_frontend_text()
        self.assertIn("TENANT_CLIENT_ENTERED_LAND_FIELDS = new Set(['approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio'])", index_source)
        self.assertIn('tenant-client-required-field', index_source)
        self.assertIn('tenant-client-complete-field', index_source)
        self.assertIn('tenant-client-required-badge', index_source)
        self.assertIn("badge.textContent = 'إدخال العميل';", index_source)
        self.assertIn('function updateClientEnteredLandFieldState(input)', index_source)
        self.assertIn("field.classList.toggle('tenant-client-complete-field', entered);", index_source)
        self.assertIn('input.addEventListener(\'input\', () => updateClientEnteredLandFieldState(input));', index_source)
        self.assertIn('refreshClientEnteredLandFieldStates();', index_source)
        self.assertIn("sectionKey === 'land_croquis' && TENANT_CLIENT_ENTERED_LAND_FIELDS.has(f.fieldKey)", index_source)

    def test_client_entered_land_fields_validation_and_placeholders(self):
        index_source = read_frontend_text()
        db_source = read_module_source('db.py')

        # DB prebuilt field placeholders
        self.assertIn("'placeholder': 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.'", db_source)
        self.assertIn("'placeholder': 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.'", db_source)
        self.assertIn("'placeholder': 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.'", db_source)

        # Validation function in index.html
        self.assertIn('function validateLandCroquisClientFields()', index_source)
        self.assertIn("key === 'land_croquis'", index_source)
        self.assertIn("validateLandCroquisClientFields()", index_source)
        self.assertIn("يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.", index_source)
        self.assertIn("يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.", index_source)
        self.assertIn("يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.", index_source)

        # toggleApproveCroquisData also validates before approving
        self.assertIn('function toggleApproveCroquisData()', index_source)
        self.assertIn('const errors = validateLandCroquisClientFields();', index_source)

    def test_financial_schedule_percentages_and_sales_exit_hiding(self):
        index_source = read_frontend_text()
        # The prototype mirror is a local-only reference asset — never tracked —
        # so its assertions only run where the file actually exists.
        proto_path = ROOT / 'THE-VIEW-Financial-Model-FINAL-v2.html'
        proto_source = proto_path.read_text(encoding='utf-8') if proto_path.exists() else ''

        # Schedule table percentage clamping
        self.assertIn('function enforceSchedulePctInput(input, fieldName)', index_source)
        if proto_source:
            self.assertIn('function enforceSchedulePctInput(input, fieldName)', proto_source)
        self.assertIn('const costPctTotal = Math.min(100, scheduleRows.reduce((s, r) => s + r.costPct, 0))', index_source)
        if proto_source:
            self.assertIn('const costPctTotal=Math.min(100,scheduleRows.reduce((s,r)=>s+r.costPct,0));', proto_source)
        self.assertIn('100 - existingCostSum', index_source)
        self.assertIn('100 - existingDevSum', index_source)

        # Section 13 sales exit dynamic hiding
        self.assertIn('id="saleExitYearWrap"', index_source)
        self.assertIn('id="saleExitCostRateWrap"', index_source)
        self.assertIn('id="resSaleExitGrossCard"', index_source)
        self.assertIn('id="resSaleExitCard"', index_source)
        self.assertIn("setWrapVisible('saleExitYearWrap', saleExitActive);", index_source)
        self.assertIn("setWrapVisible('saleExitCostRateWrap', saleExitActive);", index_source)
        self.assertIn("resSaleExitGrossCard.classList.toggle('dynamic-off', !saleExitActive);", index_source)
        self.assertIn("resSaleExitCard.classList.toggle('dynamic-off', !saleExitActive);", index_source)

    def test_financial_pdf_fallback_writes_real_arabic_text(self):
        import tempfile
        from pathlib import Path

        model = {
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 2, 'operationYears': 5,
                'landArea': 70000, 'builtUpAreaAbove': 100000, 'coverageRate': 35,
                'financeEnabled': 'no', 'fundEnabled': 'no', 'fundFeesEnabled': 'no',
                'externalEnabled': 'no', 'exitEnabled': 'no',
            },
            'tables': {
                'cashflowTable': [{'year': 1, 'final': -10, 'cumulative': -10}],
                'sensitivityTable': [{'scenario': 'أساسي', 'roi': '12%'}],
            },
            'projection': {'projectCost': 1000},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'model.pdf'
            with self.app.app_context():
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, output)
            self.assertTrue(self.application_module._financial_pdf_has_text(output))
            import fitz
            document = fitz.open(output)
            try:
                text = '\n'.join(page.get_text() for page in document)
            finally:
                document.close()
            # PyMuPDF applies no shaping, so the report must carry presentation forms.
            self.assertIn('\ufee3', text)
            self.assertIn('70,000', text)
            empty = Path(temp_dir) / 'empty.pdf'
            blank = fitz.open()
            blank.new_page()
            blank.save(empty)
            blank.close()
            self.assertFalse(self.application_module._financial_pdf_has_text(empty))

        source = read_module_source('app.py')
        # A textless PDF must never be accepted, and the font-embedding writer must be
        # tried before the MuPDF HTML engine, which needs system fonts we do not have.
        self.assertNotIn('os.path.getsize(output_path) > 0', source)
        self.assertLess(
            source.index('generate_financial_pdf_from_model(project_name, model, output_path)\n            if _financial_pdf_has_text'),
            source.index("fitz.open('html', candidate.encode('utf-8'))")
        )
        self.assertIn('def _financial_pdf_shape(text):', source)
        self.assertIn('def split_runs(value):', source)

    def test_parallel_section_approvals_are_not_lost(self):
        import threading

        client = self.app.test_client()
        headers = self._headers(self.token_a)
        sections = [
            'basic', 'location', 'land_croquis', 'section-timeline',
            'section-financial-calc', 'section-team', 'section-market-study',
            'section-executive-content',
        ]
        client.post('/api/project-draft', headers=headers, json={
            'draftData': {'draftId': 'parallel-approval', 'project_name': 'ملف اعتماد'},
            'sectionStatuses': {}, 'status': 'draft'
        })
        # The location workflow's approved state is a stored artifact — writes
        # through the real gates land it here; a save payload cannot mint it.
        with self.app.app_context():
            draft_row = db.get_project_draft_by_id(self.tenant_a, 'parallel-approval')
            draft_state = dict(draft_row['draft_data'] or {})
            draft_state['location_analysis_approved'] = True
            draft_state['tenantCreativeImages'] = {'map_approvals': {
                'overview': True, 'access': True, 'catchment': True, 'landmarks': True}}
            db.get_db().execute(
                'UPDATE project_drafts SET draft_data = ? WHERE id = ? AND tenant_id = ?',
                (json.dumps(draft_state, ensure_ascii=False), 'parallel-approval', self.tenant_a))
            db.get_db().commit()

        # One merged call must store every section.
        response = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionStatuses': {key: 'approved' for key in sections}
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = client.get('/api/project-draft', headers=headers).get_json()['draft']['section_statuses']
        self.assertEqual(sorted(stored), sorted(sections))
        self.assertTrue(all(value == 'approved' for value in stored.values()), stored)

        # And a race between single-section calls must not drop any of them either.
        client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionStatuses': {key: 'draft' for key in sections}
        })
        errors = []

        def approve(section_key):
            try:
                with self.app.test_client() as parallel:
                    parallel.post('/api/project-draft/section-status', headers=headers, json={
                        'sectionKey': section_key, 'sectionStatus': 'approved'
                    })
            except Exception as error:  # pragma: no cover - surfaced through the assertion below
                errors.append(error)

        threads = [threading.Thread(target=approve, args=(key,)) for key in sections]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        stored = client.get('/api/project-draft', headers=headers).get_json()['draft']['section_statuses']
        self.assertTrue(all(stored.get(key) == 'approved' for key in sections), stored)

        approval = client.post('/api/project-draft/request-approval', headers=headers, json={})
        self.assertEqual(approval.status_code, 200, approval.get_json())
        index_source = read_frontend_text()
        # A section nobody opened had no stored status, and the approval gate walks the stored
        # map, so the file could be submitted with that section never approved.
        self.assertIn('applySectionStatuses(initialStatuses);', index_source)
        # The save payload ships the stored map and request-approval walks it
        # server-side — a section nobody opened cannot slip through unapproved.
        self.assertIn("sectionStatuses: tenantProjectSectionStatuses", index_source)
        self.assertIn("'/api/project-draft/request-approval', { draftId", index_source)
        self.assertIn('def update_draft_section_statuses(', read_module_source('db.py'))

    def test_components_block_shows_the_regulated_uses(self):
        index_source = read_frontend_text()
        # The activities are chosen in the components table, so the regulated list belongs there.
        self.assertIn('id="componentsAllowedUsesNote"', index_source)
        self.assertIn('function renderComponentsAllowedUsesNote(allowedUses, status)', index_source)
        self.assertIn("'<span>الاستخدامات المسموحة تنظيميًا:</span> ' + escapeHtml(uses)", index_source)
        self.assertIn('renderComponentsAllowedUsesNote(allowedUses, status);', index_source)

    def test_access_road_names_do_not_change_between_regenerations(self):
        import maps_service

        site = (21.6324618, 39.1056571)
        # The probes decided which roads were found; seeding them meant a new set of street
        # names on every regeneration of the same site.
        self.assertEqual(maps_service.access_probe_points(*site), maps_service.access_probe_points(*site))
        self.assertEqual(len(maps_service.access_probe_points(*site)), 8)
        source = read_module_source('maps_service.py')
        access_at = source.index('def _draw_access_roads(')
        body = source[access_at:source.index('def _get_cached_map_images(')]
        self.assertIn('probe_points = access_probe_points(route_origin_lat, route_origin_lng)', body)
        self.assertNotIn('seed_step', body)
        self.assertNotIn('rotate_by', body)
        self.assertNotIn("regen_seed = int(", body)
        self.assertNotIn('discovered_count', body)
        self.assertIn("road_data if isinstance(road_data, list) else []", body)

        # The names the user entered in the location section win over Google's wording.
        known = [
            'شارع الشاطئ وإسطنبول', 'الامير فيصل بن فهد والخليفة المهدي',
            'الامير فيصل بن فهد', 'شارع الشاطئ', 'طريق الكورنيش الفرعي',
        ]
        self.assertEqual(maps_service.match_known_road_name('شارع الشاطئ', known), 'شارع الشاطئ')
        self.assertEqual(maps_service.match_known_road_name('طريق الأمير فيصل بن فهد', known), 'الامير فيصل بن فهد')
        self.assertEqual(maps_service.match_known_road_name('الكورنيش', known), 'طريق الكورنيش الفرعي')
        self.assertEqual(maps_service.match_known_road_name('طريق مجهول تماما', known), '')
        self.assertEqual(maps_service.match_known_road_name('', known), '')
        # A compound row and its own street are one road; drawing both repeated the name.
        self.assertTrue(maps_service.is_same_road_name(
            'الامير فيصل بن فهد والخليفة المهدي', 'طريق الأمير فيصل بن فهد'
        ))
        self.assertTrue(maps_service.is_same_road_name('شارع الشاطئ', 'الشاطئ'))
        self.assertFalse(maps_service.is_same_road_name('شارع الشاطئ', 'طريق الكورنيش'))
        self.assertFalse(maps_service.is_same_road_name('', 'شارع الشاطئ'))
        self.assertIn('is_same_road_name(result[1], accepted)', source)
        self.assertEqual(
            maps_service._road_name_key('طريق الأمير فيصل بن فهد'),
            maps_service._road_name_key('الامير فيصل بن فهد'),
        )

    def test_croquis_coordinates_become_the_site_boundary(self):
        import maps_service

        # Jeddah, UTM zone 37N. The plot below is the real croquis table of a live project,
        # whose approved area is 7,012 sqm.
        site_lat, site_lng = 21.6324618, 39.1056571
        rows = [
            {'eastings': '511085.849', 'northings': '2392264.840', 'parcel_id': 'P-1'},
            {'eastings': '511189.416', 'northings': '2392298.825', 'parcel_id': 'P-1'},
            {'eastings': '511198.442', 'northings': '2392262.273', 'parcel_id': 'P-1'},
            {'eastings': '511208.664', 'northings': '2392220.822', 'parcel_id': 'P-1'},
            {'eastings': '511196.244', 'northings': '2392219.452', 'parcel_id': 'P-1'},
            {'eastings': '511111.135', 'northings': '2392211.397', 'parcel_id': 'P-1'},
            {'eastings': '511100.913', 'northings': '2392224.147', 'parcel_id': 'P-1'},
        ]
        self.assertEqual(maps_service.utm_zone_for_longitude(site_lng), 37)
        polygon = maps_service.survey_polygon_from_project(
            {'survey_coordinates': json.dumps(rows)}, site_lat, site_lng
        )
        self.assertIsNotNone(polygon)
        self.assertEqual(len(polygon), 7)
        mean_latitude = math.radians(site_lat)
        metres = [
            ((point[1] - site_lng) * 111320 * math.cos(mean_latitude), (point[0] - site_lat) * 110540)
            for point in polygon
        ]
        area = abs(sum(
            metres[index][0] * metres[(index + 1) % len(metres)][1]
            - metres[(index + 1) % len(metres)][0] * metres[index][1]
            for index in range(len(metres))
        )) / 2
        self.assertAlmostEqual(area, 7012.12, delta=400)

        # A local grid that lands in another region must be refused, not drawn.
        self.assertIsNone(maps_service.survey_polygon_from_project(
            {'survey_coordinates': json.dumps([
                {'eastings': '1000.0', 'northings': '2000.0', 'parcel_id': 'X'},
                {'eastings': '1100.0', 'northings': '2000.0', 'parcel_id': 'X'},
                {'eastings': '1100.0', 'northings': '2100.0', 'parcel_id': 'X'},
            ])}, site_lat, site_lng
        ))

        source = read_module_source('maps_service.py')
        index_source = read_frontend_text()
        self.assertIn('def survey_polygon_from_project(', source)
        self.assertIn('Using croquis survey polygon with', source)
        self.assertIn('def _google_bounds_polygon(', source)
        # The client must send the croquis table and must not switch the highlight off just
        # because no boundary has been found yet.
        self.assertIn("'survey_coordinates', 'city'", index_source)
        self.assertIn("return source !== 'cleared';", index_source)
        clear_body = index_source.split('function clearTenantPolygonSelection()', 1)[1].split('async function confirmTenantPolygon()', 1)[0]
        self.assertIn('tenantMapDraftPolygonPoints = [];', clear_body)
        self.assertNotIn('location_polygon_source', clear_body)

    def test_map_preview_uses_the_rendered_centre_and_fits_its_content(self):
        import maps_service

        source = read_module_source('maps_service.py')
        index_source = read_frontend_text()
        # Clicks were converted against the site pin while the image is centred on the plot,
        # which put every manually drawn boundary off by that distance.
        self.assertIn("result['centers'] = {", source)
        self.assertIn("'center_lat': map_center_lat", source)
        self.assertIn('const center = (tenantCreativeImages.map_centers || {})[mapType] || {};', index_source)
        self.assertIn('tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };', index_source)

        # Nine destination rows became nine rings up to 31 km wide; keep three and frame them.
        rings = maps_service.catchment_rings([
            {'km': 1.6, 'minutes': 5}, {'km': 4.9, 'minutes': 11}, {'km': 13.6, 'minutes': 22},
            {'km': 28.6, 'minutes': 35}, {'km': 30.9, 'minutes': 38},
        ])
        self.assertEqual(len(rings), 3)
        self.assertEqual([ring['km'] for ring in rings], [1.6, 13.6, 30.9])
        self.assertEqual(rings[0]['label'], '5 دقائق')
        named_rings = maps_service.catchment_rings([{'km': 2.4, 'minutes': 7, 'label': 'حي النرجس'}])
        self.assertEqual(named_rings[0]['name'], 'حي النرجس')
        self.assertIn('حي النرجس', named_rings[0]['label'])
        markers = maps_service._build_markers(24.0, 46.0, [
            {'name': 'مجمع الراشد', 'lat': 24.01, 'lng': 46.01}
        ])
        self.assertEqual(markers[1]['label'], '1')
        self.assertEqual(markers[1]['name'], 'مجمع الراشد')
        self.assertIn('def _draw_marker_name_label(', source)
        self.assertIn("'map_label_version': MAP_LABEL_RENDER_VERSION", source)
        self.assertIn("'nearby_landmarks_data'", index_source)
        self.assertEqual(maps_service.catchment_rings([]), [])
        near = maps_service.zoom_for_radius_km(21.63, 1.6)
        far = maps_service.zoom_for_radius_km(21.63, 30.9)
        self.assertGreater(near, far)
        for radius, zoom in ((1.6, near), (30.9, far)):
            metres_per_pixel = 156543.03392 * math.cos(math.radians(21.63)) / (2 ** zoom) / 2
            self.assertLessEqual(radius * 1000 / metres_per_pixel, 720 * 0.8 + 1)
        self.assertIn('def zoom_for_radius_km(', source)
        self.assertIn('def access_map_zoom(', source)
        self.assertIn("access_zoom = access_map_zoom(lat, zooms['access'])", source)
        self.assertIn('shown_landmarks = [item for item in landmarks if item.get', source)
        self.assertIn('def find_place_near(', source)
        # Appending the project address made Google return the site itself for every landmark.
        self.assertNotIn("query = f\"{lm['name']}, {location_context}\"", source)
        self.assertIn('async function unapproveMapPreview(mapType)', index_source)
        self.assertIn("(approved ? 'unapprove' : 'approve')", index_source)

    def test_map_label_font_never_reapplies_bidi(self):
        from PIL import ImageFont
        import maps_service

        font = maps_service._get_arabic_font(24)
        self.assertEqual(font.layout_engine, ImageFont.Layout.BASIC)
        shaped = maps_service._reshape_arabic_text('طريق الشاطئ الشمالي')
        self.assertEqual(shaped[0], '\ufef2')
        self.assertEqual(shaped[-1], '\ufec3')

    def test_progress_bars_never_jump_backward(self):
        index_source = read_frontend_text()
        self.assertIn('const value = allowDecrease ? requested : Math.max(loaderProgressValue, requested);', index_source)
        self.assertIn('const continueExisting = alreadyVisible && loaderSessionActive && options.reset !== true;', index_source)
        self.assertIn('const value = Math.max(genProgressValue, requested);', index_source)
        self.assertIn('let genProgressValue = 0;', index_source)

    def test_presentation_bulk_map_regeneration_is_rejected_without_mutation(self):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant_a,
                'Old location',
                project_data={
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'tenantCreativeImages': {
                        'map_placeholders': {'##MAP_OVERVIEW##': '/old-map.png'},
                        'map_zooms': {'overview': 17},
                        'maps_persisted': True,
                    },
                },
                slides_data=[],
            )
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post(
                f'/api/presentations/{pres_id}/regenerate-maps',
                headers=self._headers(self.token_a),
                json={'projectData': {'location_lat': 25.0, 'location_lng': 47.0}}
            )

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'INDIVIDUAL_MAP_GENERATION_REQUIRED')
        generate_maps.assert_not_called()
        with self.app.app_context():
            stored = db.get_presentation(pres_id, tenant_id=self.tenant_a)
        stored_data = json.loads(stored['project_data'])
        self.assertEqual(stored_data['location_lat'], 24.0)
        self.assertEqual(stored_data['tenantCreativeImages']['map_placeholders'], {'##MAP_OVERVIEW##': '/old-map.png'})

    def test_site_analysis_fills_google_site_fields_without_touching_unknown_fields(self):
        client = self.app.test_client()
        nearby = [{'name': 'معلم قريب', 'lat': 24.001, 'lng': 46.001, 'distance_text': '1 كم'}]
        city = [{'name': 'معلم المدينة', 'lat': 24.02, 'lng': 46.02}]
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', side_effect=lambda *args, **kwargs: {'success': True, 'landmarks': nearby if kwargs.get('radius') == 20000 else city}), \
                patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[{'distance_text': '1.2 كم', 'duration_min': 5}]), \
                patch.object(self.application_module.maps_service, 'discover_nearby_roads', return_value=[{'name': 'طريق تجريبي', 'lat': 24.0, 'lng': 46.0}]), \
                patch.object(self.application_module.maps_service, '_fetch_osm_polygon', return_value=[(23.999, 45.999), (23.999, 46.001), (24.001, 46.001), (24.001, 45.999)]), \
                patch.object(self.application_module.maps_service, 'detect_curated_city', return_value=None), \
                patch.object(self.application_module.maps_service, 'get_curated_city_landmarks', return_value=[]), \
                patch.object(self.application_module.maps_service, 'get_nearest_category_landmarks', return_value=[]), \
                patch.object(self.application_module.maps_service, 'reverse_geocode_location', return_value={'formatted_address': 'Riyadh, Saudi Arabia'}), \
                patch.object(self.application_module.population_service, 'get_population_density', return_value={'available': False}), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={'placeholders': {}, 'zooms': {'overview': 17}}):
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': '24.0', 'location_lng': '46.0', 'location_address': 'https://www.google.com/maps/@24.0,46.0,17z'}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        fields = response.get_json()['fields']
        self.assertEqual(fields['main_roads'], 'طريق تجريبي')
        self.assertIn('معلم قريب', fields['nearby_landmarks'])
        self.assertIn('1.2 كم', fields['nearby_landmarks'])
        self.assertIn('5 دقيقة', fields['nearby_landmarks'])
        self.assertIn('معلم المدينة', fields['city_landmarks'])
        self.assertIn('location_polygon', fields)
        self.assertEqual(fields['location_polygon_source'], 'auto')
        self.assertNotIn('land_area', fields)

    def test_slide_plan_falls_back_when_ai_provider_is_unavailable(self):
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat_parallel', side_effect=RuntimeError('AI unavailable')) as planner:
            response = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
                'projectData': {'project_name': 'مشروع تجريبي', 'project_type': 'سكني'}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        self.assertTrue(response.get_json()['plan']['slides'])
        # A failed planner ships the generic structure, and that is stated rather than passing as
        # the model's own proposal — every such file otherwise came out with identical titles.
        self.assertEqual(response.get_json()['plan']['source'], 'fallback')
        self.assertEqual(response.get_json()['planSource'], 'fallback')
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(planner.call_args.kwargs['max_tokens'], 12000)
        self.assertEqual(planner.call_args.kwargs['timeout'], 75)
        self.assertEqual(planner.call_args.kwargs['model'], self.application_module.LUNA_TEXT_MODEL)

    def test_slide_count_has_no_upper_limit(self):
        """The plan follows the amount of content: a stored max_slides used to trim the surplus."""
        engine = self.application_module.slide_engine
        # Only a locked count binds the plan; otherwise the ceiling is open.
        self.assertEqual(engine.resolve_slide_bounds({'min_slides': 8, 'max_slides': 30})[1],
                         engine.SLIDE_COUNT_OPEN)
        self.assertEqual(engine.resolve_slide_bounds(
            {'min_slides': 8, 'max_slides': 30, 'lock_slide_count': 1, 'default_slide_count': 12}),
            (12, 12, 12))
        # Every one of the 117 content slides survives; the canonical section divider is added.
        long_plan = {'slides': (
            [{'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'}]
            + [{'title': f'محور {i}', 'type': 'content', 'bullets': ['1', '2', '3']} for i in range(117)]
            + [{'title': 'الختام', 'type': 'closing'}]
        )}
        with patch.object(self.application_module, 'call_zai_chat_parallel', return_value={}), \
                patch.object(self.application_module, 'extract_chat_content', return_value='{}'), \
                patch.object(self.application_module, 'parse_slide_plan', return_value=long_plan), \
                self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            result = self.application_module._execute_slide_plan(
                {'project_name': 'THE VIEW'}, self.tenant_a, {'min_slides': 8, 'max_slides': 30})
        self.assertEqual(len(result['plan']['slides']), 121)
        self.assertEqual(sum(slide.get('type') == 'content' for slide in result['plan']['slides']), 117)
        self.assertEqual(result['plan']['source'], 'model')
        self.assertNotIn('Too many slides', ' '.join(result['validation']['issues']))

        app_source = read_module_source('app.py')
        self.assertIn('max_tokens=12000', app_source)
        self.assertIn('timeout=75', app_source)
        self.assertIn('model=LUNA_TEXT_MODEL', app_source)
        self.assertNotIn('timeout=600', app_source)
        self.assertNotIn('شريحة كحد أقصى)', app_source)

        index_source = read_frontend_text()
        # Regeneration always re-plans, and the previous deck is never displayed while it runs.
        self.assertIn("clearTenantSlidesStage('جاري إعداد خطة وهيكل العرض')", index_source)
        self.assertIn('const planResponse = await requestTenantSlidePlan(tenantProjectData', index_source)
        self.assertNotIn('if (!tenantSlidePlan) {', index_source)
        self.assertNotIn('settingsMaxSlides', index_source)

    def test_slide_renumbering_updates_legacy_footers_totals_and_index(self):
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        project = {'project_name': 'المشروع'}
        content = lambda title: engine.postprocess_slide(
            f'<div class="slide"><p>{title}</p></div>', 'content', slide_num=98,
            slide_title=title, total_slides=99, branding=branding, project_data=project,
        )
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس قديم</div>'},
            {'title': 'نبذة عن المشروع', 'type': 'section_divider', 'section_key': 'overview',
             'html': engine.build_section_divider_slide(
                 {'title': 'نبذة عن المشروع'}, 88, 99, branding, project)},
            {'title': 'ملخص المشروع', 'type': 'content', 'section_key': 'overview',
             'html': content('ملخص المشروع')},
            {'title': 'الدراسة المالية', 'type': 'section_divider', 'section_key': 'financial',
             'html': engine.build_section_divider_slide(
                 {'title': 'الدراسة المالية'}, 90, 99, branding, project)},
            {'title': 'مؤشرات الاستثمار', 'type': 'content', 'section_key': 'financial',
             'html': content('مؤشرات الاستثمار')},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]

        renumbered = engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project)
        self.assertEqual(len(renumbered), 7)
        self.assertIn('data-slide-counter="1"', renumbered[2]['html'])
        self.assertIn('03 — 07', renumbered[2]['html'])
        self.assertIn('data-slide-counter="1"', renumbered[3]['html'])
        self.assertIn('04 — 07', renumbered[3]['html'])
        self.assertIn('05 — 07', renumbered[4]['html'])
        self.assertIn('06 — 07', renumbered[5]['html'])
        self.assertNotIn('data-slide-footer', renumbered[0]['html'])
        self.assertNotIn('data-slide-footer', renumbered[-1]['html'])
        self.assertRegex(renumbered[1]['html'], r'data-index-page="overview"[^>]*>03</div>')
        self.assertRegex(renumbered[1]['html'], r'data-index-page="financial"[^>]*>05</div>')
        self.assertRegex(renumbered[1]['html'], r'data-index-page="closing"[^>]*>07</div>')
        self.assertEqual(renumbered, engine.renumber_presentation_slides(
            renumbered, branding=branding, project_data=project))

        index_source = read_frontend_text()
        self.assertIn('function renumberTenantSlides()', index_source)
        self.assertIn('renumberTenantSlides();\n      renderTenantSlides();', index_source)
        create_source = index_source.split('async function saveTenantPresentation', 1)[1].split('async function openExistingPresentation', 1)[0]
        update_source = index_source.split('async function saveExistingPresentation', 1)[1].split('async function regeneratePresentationMaps', 1)[0]
        export_source = index_source.split('async function exportTenantSlides', 1)[1].split('async function deleteTenantPresentation', 1)[0]
        self.assertLess(create_source.index('renumberTenantSlides();'), create_source.index("api('POST', '/api/presentations'"))
        self.assertLess(update_source.index('renumberTenantSlides();'), update_source.index("api('PUT', '/api/presentations/'"))
        self.assertLess(export_source.index('renumberTenantSlides();'), export_source.index('const payload = {'))
        self.assertIn('slidesData: tenantSlidesData', export_source)

    def test_index_slide_rebuilds_and_renumbers_decks_without_dividers(self):
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
            'accent_color': '#C4A35A', 'background_color': '#ffffff',
            'text_color': '#111111', 'company_name': 'شركة الاختبار',
        }
        project = {'project_name': 'مشروع بدون فواصل'}
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide"></div>'},
            {'title': 'نبذة عن المشروع', 'type': 'content', 'section_key': 'overview', 'html': '<div class="slide">محتوى 1</div>'},
            {'title': 'بيانات الأرض', 'type': 'content', 'section_key': 'land', 'html': '<div class="slide">محتوى 2</div>'},
            {'title': 'موقع المشروع', 'type': 'content', 'section_key': 'location', 'html': '<div class="slide">محتوى 3</div>'},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        renumbered = engine.renumber_presentation_slides(slides, branding=branding, project_data=project)
        self.assertEqual(len(renumbered), 6)
        index_html = renumbered[1]['html']
        self.assertIn('data-index-section="overview"', index_html)
        self.assertIn('data-index-section="land"', index_html)
        self.assertIn('data-index-section="location"', index_html)
        self.assertRegex(index_html, r'data-index-page="overview"[^>]*>03')
        self.assertRegex(index_html, r'data-index-page="land"[^>]*>04')
        self.assertRegex(index_html, r'data-index-page="location"[^>]*>05')

    def test_presentation_save_update_and_export_enforce_slide_numbers(self):
        engine = self.application_module.slide_engine
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        with self.app.app_context():
            branding = db.get_branding(self.tenant_a) or {}
        stale_content = engine.postprocess_slide(
            '<div class="slide"><p>محتوى</p></div>', 'content', slide_num=8,
            slide_title='محتوى', total_slides=9, branding=branding,
        )
        slides = [
            {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'},
            {'title': 'محتويات العرض', 'type': 'index', 'html': '<div class="slide">فهرس</div>'},
            {'title': 'محتوى', 'type': 'content', 'section_key': 'overview', 'html': stale_content},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض الترقيم', 'projectData': {'project_name': 'عرض الترقيم'},
            'slidesData': slides, 'slideCount': 99,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']
        with self.app.app_context():
            stored = db.get_presentation(presentation_id, tenant_id=self.tenant_a)
            stored_slides = json.loads(stored['slides_data'])
        self.assertEqual(stored['slide_count'], 4)
        self.assertIn('03 — 04', stored_slides[2]['html'])

        loaded = client.get('/api/presentations/' + presentation_id, headers=headers).get_json()['presentation']
        self.assertIn('03 — 04', loaded['slidesData'][2]['html'])
        loaded_slides = loaded['slidesData']
        loaded_slides.insert(3, {
            'title': 'محتوى إضافي', 'type': 'content', 'section_key': 'overview', 'html': stale_content,
        })
        updated = client.put('/api/presentations/' + presentation_id, headers=headers, json={
            'slidesData': loaded_slides, 'slideCount': 99,
        })
        self.assertTrue(updated.get_json()['success'], updated.get_json())
        with self.app.app_context():
            stored = db.get_presentation(presentation_id, tenant_id=self.tenant_a)
            stored_slides = json.loads(stored['slides_data'])
        self.assertEqual(stored['slide_count'], 5)
        self.assertIn('03 — 05', stored_slides[2]['html'])
        self.assertIn('04 — 05', stored_slides[3]['html'])

        with patch('exports.pdf_export.generate_pdf') as generate_pdf:
            exported = client.post('/api/export', headers=headers, json={
                'format': 'pdf', 'presentationId': presentation_id, 'projectName': 'عرض الترقيم',
            })
        self.assertTrue(exported.get_json()['success'], exported.get_json())
        exported_html = generate_pdf.call_args.args[0]
        self.assertIn('03 — 05', exported_html)
        self.assertIn('04 — 05', exported_html)
