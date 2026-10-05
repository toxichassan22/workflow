class MeetingRequirementsTestsPart05MapFraming(MeetingRequirementsTests):

    def test_map_hydration_restores_the_rendered_size_and_baked_frame(self):
        module = self.application_module
        center = {'lat': 24.0, 'lng': 46.0, 'width': 974, 'height': 548}
        sibling = {'lat': 24.01, 'lng': 46.01, 'zoom': 15, 'width': 375, 'height': 211}
        with tempfile.NamedTemporaryFile(dir=self.temp_dir.name, suffix='.png') as image:
            metadata = {'lat': 24.0, 'lng': 46.0, 'center_lat': 24.0, 'center_lng': 46.0,
                        'zoom': 18, 'viewport_size': {'width': 974, 'height': 548}}
            record = {'image_type': 'overview', 'placeholder': '##MAP_OVERVIEW##',
                      'file_path': image.name, 'metadata_json': json.dumps(metadata)}
            project = {'tenantCreativeImages': {'map_baked_frames': {
                'overview': {'lat': 24.1, 'lng': 46.1, 'zoom': 17}, 'access': sibling}}}
            with patch.object(module.db, 'get_map_images', return_value=[record]):
                hydrated = module._merge_persisted_map_assets(project, self.tenant_a, draft_id='frame-restore')
        creative = hydrated['tenantCreativeImages']
        self.assertEqual(creative['map_centers']['overview'], center)
        self.assertEqual(creative['map_baked_frames']['overview'], {**center, 'zoom': 18})
        self.assertEqual(creative['map_baked_frames']['access'], sibling)

    def test_map_approval_refuses_a_different_size_or_small_high_zoom_pan(self):
        module = self.application_module
        frame = {'lat': 24.0, 'lng': 46.0, 'width': 974, 'height': 548, 'zoom': 18}
        creative = {'map_viewport_overrides': {'overview': True},
                    'map_baked_frames': {'overview': frame}, 'map_zooms': {'overview': 18},
                    'map_centers': {'overview': {key: value for key, value in frame.items() if key != 'zoom'}}}
        self.assertTrue(module._frame_matches_baked(creative, 'overview'))
        for change in ({'width': 375, 'height': 211}, {'lat': 24.00001}, {'lng': 46.00001}):
            with self.subTest(change=change):
                creative['map_centers']['overview'] = {**frame, **change}
                self.assertFalse(module._frame_matches_baked(creative, 'overview'))

    def test_map_preview_uses_the_rendered_centre_and_fits_its_content(self):
        import maps_service

        source = read_module_source('maps_service.py')
        index_source = read_frontend_text()
        # Clicks were converted against the site pin while the image is centred on the plot,
        # which put every manually drawn boundary off by that distance.
        self.assertIn("result['centers'] = {", source)
        self.assertIn("'center_lat': overview_center_lat", source)
        self.assertIn('const center = (tenantCreativeImages.map_centers || {})[mapType] || {};', index_source)
        self.assertIn('const bakedFrame = (tenantCreativeImages.map_baked_frames || {})[mapType] || {};', index_source)
        self.assertIn('tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), [mapType]: data.centers[mapType] };', index_source)

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
        self.assertNotIn('unapproveMapPreview', index_source)
        self.assertNotIn('approveMapPreview', index_source)
