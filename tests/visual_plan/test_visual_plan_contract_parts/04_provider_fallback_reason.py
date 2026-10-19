class VisualPlanContractTestsPart04(VisualPlanContractBase):
    def test_provider_failure_is_reported_without_a_deterministic_layout(self):
        module = self.application_module
        project = self.project()
        project['approved_coverage_ratio'] = 90
        workflow = self.workflow(project)
        workflow['distribution']['rows'][0]['floor_area_sqm'] = 900

        with patch.object(module, 'call_openrouter_chat', return_value={
                'error': 'provider unavailable'}), \
                patch.object(module, 'persist_generated_image',
                             return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model',
                             return_value='ref:parcel'), \
                patch.object(module, '_require_billing_balance', return_value=None):
            with self.app.test_request_context():
                module.g.tenant_id = self.tenant_a
                with self.assertRaises(module.visual_plan_geometry.PlanGeometryError) as err:
                    module._visual_plan_create_scene({'projectData': project, 'plansWorkflow': workflow})
                self.assertEqual(err.exception.code, 'PLANS_PROVIDER_FAILED')
                self.assertNotIn('راجع', str(err.exception))
                self.assertNotIn('قلّل', str(err.exception))

