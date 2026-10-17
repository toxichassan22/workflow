class VisualPlanContractTestsPart03(VisualPlanContractBase):
    def test_omitted_approved_site_area_retries_and_returns_a_complete_plan(self):
        module = self.application_module
        project = self.project()
        project['project_components_data'].append({
            'name': 'Swimming Pool', 'useType': 'amenity', 'units': 1, 'builtArea': 40,
        })
        workflow = self.workflow(project)
        workflow['distribution']['rows'].append({
            'id': 'pool_row', 'building': 'Site', 'floor_range': 'Site',
            'component': 'Swimming Pool', 'units_per_floor': 1,
            'floor_area_sqm': 40, 'circulation': '',
        })
        rejected_layout = json.dumps({
            'buildings': [{'id': 'b1',
                           'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': [],
        })
        client = self.app.test_client()

        complete_layout = json.dumps({
            'buildings': [{'id': 'b1', 'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [],
            'openAreas': [{'id': 'pool_area', 'componentId': 'pool_row', 'kind': 'site_facility',
                           'polygon': [[20, 18], [28, 18], [28, 23], [20, 23]]}],
        })
        with patch.object(module, 'call_openrouter_chat', side_effect=[
                {'choices': [{'message': {'content': rejected_layout}}]},
                {'choices': [{'message': {'content': complete_layout}}]},
        ]) as model_call, \
                patch.object(module, 'persist_generated_image',
                             return_value='/uploads/creative/reference.png'), \
                patch.object(module, '_prepare_image_reference_for_model',
                             return_value='ref:parcel'):
            response = client.post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})

        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertTrue(body['success'], body)
        self.assertEqual(model_call.call_count, 2)
        retry_prompt = model_call.call_args_list[1].args[1]
        self.assertIn('pool_row', retry_prompt)
        self.assertIn('every nonparking componentId exactly once', retry_prompt)
        self.assertIn('Surface parking may use multiple openAreas', retry_prompt)
        pool_area = next(item for item in body['scene']['openAreas']
                         if item['componentId'] == 'pool_row')
        self.assertAlmostEqual(abs(module.visual_plan_geometry.signed_area(pool_area['polygon'])), 40)

    def test_pool_padel_and_landscape_components_are_typed_site_items(self):
        module = self.application_module
        components = [
            {'id': 'pool', 'name': 'Swimming Pool', 'useType': 'amenity',
             'units': 1, 'builtArea': 120},
            {'id': 'padel', 'name': 'Padel Court', 'useType': 'amenity',
             'units': 1, 'builtArea': 200},
            {'id': 'green', 'name': 'Green Area', 'useType': 'landscape',
             'units': 1, 'builtArea': 300},
            {'id': 'amenity_court', 'name': 'Amenity Court', 'useType': 'amenity',
             'notes': 'Outdoor padel court', 'units': 1, 'builtArea': 180},
        ]
        contract = {'distribution': {'rows': [
            {'id': 'pool_row', 'building': 'Site', 'floor_range': 'Ground',
             'component': 'Swimming Pool', 'floor_area_sqm': 120,
             'units_per_floor': 1, 'circulation': ''},
            {'id': 'padel_row', 'building': 'Site', 'floor_range': 'Ground',
             'component': 'Padel Court', 'floor_area_sqm': 200,
             'units_per_floor': 1, 'circulation': ''},
            {'id': 'green_row', 'building': 'Site', 'floor_range': 'Ground',
             'component': 'Green Area', 'floor_area_sqm': 300,
             'units_per_floor': 1, 'circulation': ''},
            {'id': 'amenity_court_row', 'building': 'Site', 'floor_range': 'Ground',
             'component': 'Amenity Court', 'floor_area_sqm': 180,
             'units_per_floor': 1, 'circulation': ''},
        ]}}

        program = module._visual_plan_program(contract, {'components': components})

        self.assertEqual({item['id']: item['siteType'] for item in program['siteItems']}, {
            'pool_row': 'pool', 'padel_row': 'padel', 'green_row': 'landscape',
            'amenity_court_row': 'padel',
        })
        self.assertEqual(program['buildings'], [])

    def test_site_svg_shows_project_identity_roads_building_ids_and_amenities(self):
        module = self.application_module
        polygon = [[0, 0], [40, 0], [40, 30], [0, 30]]
        geometry = {'parcels': [{'id': 'parcel_1', 'polygon': polygon}]}
        contract = {
            'geometry': geometry, 'projectName': 'مشروع النخيل', 'landArea': 1200,
            'primaryFrontage': {'direction': 'west'},
            'directions': [{'direction': 'west', 'street': True, 'streetName': 'West Road',
                            'streetWidth': 18}],
        }
        buildings = [
            {'id': 'tower_a', 'footprint': [[8, 8], [14, 8], [14, 14], [8, 14]]},
            {'id': 'unit_1_001', 'footprint': [[20, 5], [23, 5], [23, 8], [20, 8]]},
            {'id': 'unit_1_002', 'footprint': [[24, 5], [27, 5], [27, 8], [24, 8]]},
        ]
        site_areas = [
            {'id': 'pool_area', 'componentId': 'pool_row', 'kind': 'site_facility',
             'polygon': [[20, 12], [26, 12], [26, 16], [20, 16]]},
            {'id': 'padel_area', 'componentId': 'padel_row', 'kind': 'site_facility',
             'polygon': [[27, 12], [34, 12], [34, 16], [27, 16]]},
            {'id': 'green_area', 'componentId': 'green_row', 'kind': 'landscape',
             'polygon': [[15, 20], [26, 20], [26, 25], [15, 25]]},
            {'id': 'parking_area_a', 'componentId': 'parking_row', 'kind': 'surface_parking',
             'polygon': [[2, 2], [4, 2], [4, 4], [2, 4]]},
            {'id': 'parking_area_b', 'componentId': 'parking_row', 'kind': 'surface_parking',
             'polygon': [[5, 2], [7, 2], [7, 4], [5, 4]]},
        ]
        scene = {
            'geometry': geometry, 'buildings': buildings,
            'entries': [{'id': 'main_entry', 'kind': 'main', 'buildingId': 'tower_a',
                         'side': 'west', 'position': 0.5}],
            'openAreas': site_areas,
        }
        program = {
            'buildings': [
                {'id': 'tower_a', 'label': 'Tower A',
                 'bands': [{'kind': 'ground', 'category': 'residential'}]},
                {'id': 'unit_1_001', 'label': 'Villas',
                 'bands': [{'kind': 'ground', 'category': 'residential'}]},
                {'id': 'unit_1_002', 'label': 'Villas',
                 'bands': [{'kind': 'ground', 'category': 'residential'}]},
            ],
            'siteItems': [
                {'id': 'pool_row', 'name': 'Swimming Pool', 'label': 'Swimming Pool',
                 'siteType': 'pool', 'category': 'amenity'},
                {'id': 'padel_row', 'name': 'Padel Court', 'label': 'Padel Court',
                 'siteType': 'padel', 'category': 'amenity'},
                {'id': 'green_row', 'name': 'Green Area', 'label': 'Green Area',
                 'siteType': 'landscape', 'category': 'landscape'},
                {'id': 'parking_row', 'name': 'Parking', 'label': 'Parking',
                 'siteType': 'parking', 'category': 'parking'},
            ],
        }
        with patch.object(module.visual_plan_scene, 'buildable_envelopes', return_value=[]):
            layout = module._visual_plan_site_projected_layout(
                scene, contract, program, {'developerName': 'شركة النخيل للتطوير'})

        self.assertEqual(layout['identity']['projectName'], 'مشروع النخيل')
        self.assertEqual(layout['identity']['developerName'], 'شركة النخيل للتطوير')
        self.assertEqual(layout['streets'][0]['label'], 'West Road, 18 m')
        self.assertEqual(layout['buildings'][1]['displayLabel'], 'V 1')
        self.assertTrue(layout['siteCirculation'])
        self.assertEqual({item['featureType'] for item in layout['openAreas']},
                         {'pool', 'padel', 'landscape', 'parking'})
        self.assertEqual({item['category'] for item in layout['architecturalColorLegend']},
                         {'residential', 'pool', 'padel', 'landscape', 'parking'})

        coordinates = module._visual_plan_site_coordinates_fragment(layout)
        access = module._visual_plan_site_access_fragment(layout)
        components = module._visual_plan_site_component_fragment(layout)
        landscape = module._visual_plan_site_landscape_fragment(layout)
        legend = module._visual_plan_site_legend_fragment(layout)
        self.assertIn('ll-page-background', coordinates)
        self.assertIn('class="ll-street"', coordinates)
        self.assertIn('West Road, 18 m', access)
        self.assertIn('class="ll-access-road"', access)
        self.assertIn('class="ll-internal-road"', access)
        self.assertIn('>V 1</', components)
        self.assertIn('data-site-feature="pool"', landscape)
        self.assertIn('data-site-feature="padel"', landscape)
        self.assertEqual(landscape.count('Parking'), 1)
        self.assertIn('مشروع النخيل', legend)
        self.assertIn('شركة النخيل للتطوير', legend)
        self.assertIn('BUILDING SCHEDULE', legend)

    def test_legend_edits_keep_the_saved_project_identity(self):
        module = self.application_module
        layout = {
            'legendBounds': [1212, 40, 352, 820],
            'identity': {'projectName': 'مشروع النخيل', 'developerName': 'شركة النخيل'},
            'buildingSchedule': [], 'architecturalColorLegend': [], 'streets': [],
        }
        original_legend = module._visual_plan_site_legend_fragment(layout)
        current_svg = module._visual_plan_site_svg_from_blocks({
            'coordinates': '<g id="ll-section-coordinates"/>',
            'colors': '<defs xmlns="http://www.w3.org/2000/svg" id="ll-section-colors"/>',
            'components': '<g id="ll-section-components"/>',
            'access': '<g id="ll-section-access"/>',
            'landscape': '<g id="ll-section-landscape"/>',
            'legend': original_legend,
        })
        changed = module._visual_plan_site_section_fragment(
            '<g id="ll-section-legend"><text>SITE FEATURES</text></g>', 'legend',
            allowed_text=['SITE FEATURES'])
        preserved = module._visual_plan_site_retain_project_identity(changed, current_svg)

        self.assertIn('مشروع النخيل', preserved)
        self.assertIn('شركة النخيل', preserved)
