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
            response = self.app.test_client().post(
                '/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})

        self.assertNotEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'PLANS_PROVIDER_FAILED')
        self.assertNotIn('scene', response.get_json())
        self.assertNotIn('راجع', response.get_json()['error'])
        self.assertNotIn('قلّل', response.get_json()['error'])
