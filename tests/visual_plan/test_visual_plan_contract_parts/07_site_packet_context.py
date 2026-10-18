class VisualPlanContractTestsPart07(VisualPlanContractBase):
    def test_site_packet_compacts_redundant_project_data_and_discards_stale_layout(self):
        module = self.application_module
        old_components = [{'id': 'deleted-villa', 'name': 'فلل محذوفة', 'builtArea': 12000}]
        project = {
            'approved_financial_area': '24912.95',
            'croquis_land_area': '1000',
            'project_components_data': '[]',
            'financial_study_model': {'dynamicRows': {'components': old_components}},
            'unrelated_project_blob': 'X' * 100000,
            'land_documents_analysis': {
                'summary': 'ملخص اشتراطات الأرض الحالي.',
                'rawText': 'Y' * 100000,
                'extraction_diagnostics': {'rawResponse': 'Z' * 100000},
                'parcels': [{'setbacks': '3 م من الجهات الأربع.',
                             'regulatory_constraints': 'مدخل السيارات من الغرب.'}],
            },
        }
        workflow = {
            'distribution': {'rows': [{'id': 'parking', 'component': 'مواقف حالية',
                                       'floor_area_sqm': 9000, 'notes': 'إبقاء ممر الخدمة مفتوحًا.'}]},
            'distributionNotes': 'الملاحظات الحالية للتوزيع.',
            'boundary': {'points': []},
        }
        data = {'projectData': project, 'plansWorkflow': workflow}
        signature = module._visual_plan_site_context_signature(data)
        workflow['scene'] = {
            'version': module.VISUAL_PLAN_SCENE_VERSION,
            'inputSignature': 'previous-input-signature',
            'buildings': [{'id': 'deleted-villa', 'name': 'فلل محذوفة'}],
        }

        with module.app.test_request_context('/'):
            module.g.tenant_id = self.tenant_a
            packet, _contract, _context, current_signature = module._visual_plan_site_packet(data)

        encoded_packet = json.dumps(packet, ensure_ascii=False)
        self.assertEqual(current_signature, signature)
        self.assertEqual(packet['projectMeasurements']['landAreaSqm'], 24912.95)
        self.assertEqual(packet['projectMeasurements']['croquisLandAreaSqm'], '1000')
        self.assertEqual(packet['financialComponents'], [])
        self.assertEqual(packet['distributionRows'][0]['notes'], 'إبقاء ممر الخدمة مفتوحًا.')
        self.assertEqual(packet['distributionNotes'], 'الملاحظات الحالية للتوزيع.')
        self.assertEqual(packet['landAndRegulations']['landDocumentsAnalysis']['summary'],
                         'ملخص اشتراطات الأرض الحالي.')
        self.assertNotIn('sourceProjectData', packet)
        self.assertNotIn('rawText', encoded_packet)
        self.assertNotIn('deleted-villa', encoded_packet)
        self.assertIsNone(packet['existingGeneratedLayout'])
        self.assertLess(len(encoded_packet), 20000)

    def test_site_svg_removes_unapproved_names_and_all_nonlegend_text(self):
        module = self.application_module
        raw = ('<g id="ll-section-components"><rect x="1" y="2" width="3" height="4"/>'
               '<text>Tower A</text><text>U Cluster</text><text>1,040 m2</text></g>')
        cleaned = module._visual_plan_site_section_fragment(
            raw, 'components', allowed_text=['Tower A'])
        self.assertIn('Tower A', cleaned)
        self.assertNotIn('U Cluster', cleaned)
        self.assertNotIn('1,040 m2', cleaned)

        legend = ('<g id="ll-section-legend"><text>Architectural Color</text>'
                  '<text>Health Club</text><text>Residential</text></g>')
        cleaned_legend = module._visual_plan_site_section_fragment(
            legend, 'legend', allowed_text=['Architectural Color', 'Residential'])
        self.assertIn('Architectural Color', cleaned_legend)
        self.assertIn('Residential', cleaned_legend)
        self.assertNotIn('Health Club', cleaned_legend)
