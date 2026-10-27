class MeetingRequirementsTestsPart14(MeetingRequirementsTests):

    def test_market_search_layer_is_the_browse_agent(self):
        """Summary research uses the source-scoped Playwright/SearXNG layer."""
        module = self.application_module
        self.assertFalse(hasattr(module, '_call_market_study_model'))
        self.assertFalse(hasattr(module, 'MARKET_SEARCH_ENGINE'))
        app_source = read_module_source('app.py')
        self.assertNotIn('openrouter:web_search', app_source)
        self.assertIn('_run_market_summary_research', app_source)
        self.assertIn("search_provider='searxng'", app_source)
        # One provider-native search remains: the summary researcher's own
        # plugin call. A second occurrence anywhere is the deleted paid layer
        # coming back.
        self.assertEqual(app_source.count("'id': 'web'"), 1)
        self.assertIn("browse_kwargs['plugins'] = [{'id': 'web', 'max_results': 5}]",
                      app_source)
        self.assertIn('_browse_agent_call(', app_source)
