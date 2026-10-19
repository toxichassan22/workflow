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

    def test_site_svg_extract_checkpoints_and_ensure_section_markers(self):
        module = self.application_module
        raw_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840">'
            '<defs id="ll-section-colors"><style>.main { fill: #07182C; }</style></defs>'
            '<g id="ll-section-coordinates"><rect x="0" y="0" width="1400" height="840"/></g>'
            '<g id="ll-section-components"><rect x="10" y="10" width="100" height="50"/></g>'
            '</svg>'
        )
        marked = module._visual_plan_site_ensure_section_markers(raw_svg)
        for section in ('coordinates', 'colors', 'components', 'access', 'landscape', 'legend'):
            self.assertIn(f'<!-- LL_SECTION_START:{section} -->', marked)
            self.assertIn(f'<!-- LL_SECTION_END:{section} -->', marked)

        checkpoints = module._visual_plan_site_extract_checkpoints(marked)
        self.assertIn('coordinates', checkpoints)
        self.assertIn('colors', checkpoints)
        self.assertIn('components', checkpoints)
        self.assertIn('ll-section-components', checkpoints['components'])

    def test_site_plan_assistant_generates_direct_svg_from_argon(self):
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        argon_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840">'
            '<!-- LL_SECTION_START:coordinates -->'
            '<g id="ll-section-coordinates"><rect width="1400" height="840" fill="#f8fafc"/></g>'
            '<!-- LL_SECTION_END:coordinates -->'
            '<!-- LL_SECTION_START:colors -->'
            '<defs id="ll-section-colors"></defs>'
            '<!-- LL_SECTION_END:colors -->'
            '<!-- LL_SECTION_START:components -->'
            '<g id="ll-section-components"><rect x="50" y="50" width="200" height="100" fill="#3B82F6"/></g>'
            '<!-- LL_SECTION_END:components -->'
            '<!-- LL_SECTION_START:access -->'
            '<g id="ll-section-access"></g>'
            '<!-- LL_SECTION_END:access -->'
            '<!-- LL_SECTION_START:landscape -->'
            '<g id="ll-section-landscape"></g>'
            '<!-- LL_SECTION_END:landscape -->'
            '<!-- LL_SECTION_START:legend -->'
            '<g id="ll-section-legend"></g>'
            '<!-- LL_SECTION_END:legend -->'
            '</svg>'
        )
        data = {'projectData': project, 'plansWorkflow': workflow}
        interview = {
            'success': True, 'readyForGeneration': True, 'generateRequested': True,
            'needsClarification': False,
            'assistantState': {
                'status': 'ready', 'summary': '', 'turns': [], 'answers': [],
                'pendingQuestion': '', 'readyForGeneration': True, 'generateRequested': True,
                'redesignRequested': False, 'designSpec': None, 'checkpoints': {},
                'promptTokens': 0, 'compactionCount': 0, 'compactedAtTokens': 0,
                'renderRevision': module._VISUAL_PLAN_SITE_RENDER_REVISION,
            },
            'svgCode': argon_svg,
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, 'persist_generated_image', return_value='/uploads/creative/test.svg'):
                result = module._visual_plan_site_generate(data, interview)
        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/test.svg')
        self.assertIn('ll-section-components', result['svgCode'])
        self.assertEqual(result['assistantState']['status'], 'review')

    def test_site_plan_assistant_edits_direct_svg(self):
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        existing_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840">'
            '<!-- LL_SECTION_START:coordinates -->'
            '<g id="ll-section-coordinates"><rect width="1400" height="840" fill="#f8fafc"/></g>'
            '<!-- LL_SECTION_END:coordinates -->'
            '<!-- LL_SECTION_START:colors -->'
            '<defs id="ll-section-colors"></defs>'
            '<!-- LL_SECTION_END:colors -->'
            '<!-- LL_SECTION_START:components -->'
            '<g id="ll-section-components"><rect x="50" y="50" width="200" height="100"/></g>'
            '<!-- LL_SECTION_END:components -->'
            '<!-- LL_SECTION_START:access -->'
            '<g id="ll-section-access"></g>'
            '<!-- LL_SECTION_END:access -->'
            '<!-- LL_SECTION_START:landscape -->'
            '<g id="ll-section-landscape"></g>'
            '<!-- LL_SECTION_END:landscape -->'
            '<!-- LL_SECTION_START:legend -->'
            '<g id="ll-section-legend"></g>'
            '<!-- LL_SECTION_END:legend -->'
            '</svg>'
        )
        updated_svg = existing_svg.replace('width="200"', 'width="300"')
        data = {
            'projectData': project,
            'plansWorkflow': {
                **workflow,
                'siteAssistant': {
                    'renderRevision': module._VISUAL_PLAN_SITE_RENDER_REVISION,
                    'inputSignature': module._visual_plan_site_context_signature({'projectData': project, 'plansWorkflow': workflow}),
                },
            },
            'siteSvgCode': existing_svg,
            'instruction': 'Make the building wider',
        }
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, '_visual_plan_site_call', return_value=({
                'clear': True,
                'svgCode': updated_svg,
                'reply': 'Expanded the building width.',
            }, 100)), patch.object(module, 'persist_generated_image', return_value='/uploads/creative/edited.svg'):
                result = module._visual_plan_site_edit(data)
        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/edited.svg')
        self.assertIn('width="300"', result['svgCode'])
