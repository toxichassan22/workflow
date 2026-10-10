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
