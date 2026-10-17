class VisualPlanContractTestsPart02(VisualPlanContractBase):
    def test_site_svg_generation_does_not_reuse_checkpoints_for_old_inputs(self):
        module = self.application_module
        layout = {'approvedLabels': ['Tower A'], 'parcels': [{
            'id': 'parcel_1', 'points': [[0, 0], [10, 0], [10, 8], [0, 8]],
        }], 'buildableEnvelopes': [], 'legendBounds': [1212, 40, 352, 820], 'entries': [],
            'openAreas': [], 'buildings': [{
            'id': 'b1', 'label': 'Tower A', 'category': 'residential',
            'footprint': [[1, 1], [3, 1], [3, 3], [1, 3]],
        }], 'architecturalColorLegend': [
            {'label': 'Residential', 'category': 'residential', 'color': '#B9D1EB'}]}
        packet = {'drawingLayout': layout}
        stale = {name: '<g id="ll-section-' + name + '"><text>U Cluster</text></g>'
                 for name in ('coordinates', 'colors', 'components', 'access', 'landscape', 'legend')}
        state = module._visual_plan_site_state({'plansWorkflow': {'siteAssistant': {
            'inputSignature': 'current', 'renderRevision': 1,
        }}}, 'current')
        interview = {'readyForGeneration': True, 'assistantState': state}
        data = {'plansWorkflow': {'siteAssistant': {
            'inputSignature': 'old-input', 'renderRevision': 2, 'checkpoints': stale,
        }}}
        with patch.object(module, '_visual_plan_site_packet',
                          return_value=(packet, {}, {}, 'current')), \
                patch.object(module, '_visual_plan_site_call', side_effect=AssertionError(
                    'SVG generation must render the validated scene without model calls')) as model_call, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/plan.svg'), \
                self.app.test_request_context('/'):
            module.g.tenant_id = self.tenant_a
            result = module._visual_plan_site_generate(data, interview)

        model_call.assert_not_called()
        self.assertIn('Tower A', result['svgCode'])
        self.assertIn('SITE FEATURES', result['svgCode'])
        self.assertIn('PROJECT SITE PLAN', result['svgCode'])
        self.assertEqual(result['svgCode'].count('data-building-id="b1"'), 1)
        self.assertNotIn('U Cluster', result['svgCode'])
        self.assertNotIn('Recorded Survey Coordinates', result['svgCode'])
        self.assertEqual(result['assistantState']['renderRevision'],
                         module._VISUAL_PLAN_SITE_RENDER_REVISION)

    def test_temporary_svg_model_comparison_route_is_retired(self):
        module = self.application_module
        routes = {rule.rule for rule in module.app.url_map.iter_rules()}
        self.assertFalse(any(path.startswith('/api/visual-concept/plans-svg-playground')
                             for path in routes))

    def test_recorded_survey_geometry_needs_no_separate_boundary_approval(self):
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        workflow['boundary'] = {'approved': False, 'points': project['survey_coordinates']}
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            error = module._visual_concept_plan_workflow_error(
                {'projectData': project, 'plansWorkflow': workflow},
                'plan_site', require_distribution=True)
        self.assertIsNone(error)

    def test_live_land_geometry_wins_over_legacy_saved_boundary_points(self):
        module = self.application_module
        project = self.project()
        legacy_points = [
            {'point': 'old-1', 'eastings': 1, 'northings': 1},
            {'point': 'old-2', 'eastings': 2, 'northings': 1},
            {'point': 'old-3', 'eastings': 2, 'northings': 2},
        ]
        _project, _workflow, _boundary, points, context = \
            module._visual_concept_plans_context_from_request({
                'projectData': project,
                'plansWorkflow': {'boundary': {'points': legacy_points}},
            })
        self.assertEqual(points, module._visual_concept_plan_boundary_points(project['survey_coordinates']))
        self.assertEqual(context['boundary_points'], points)
