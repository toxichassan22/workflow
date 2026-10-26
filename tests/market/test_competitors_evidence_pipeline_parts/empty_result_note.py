from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline


class EmptyResultNoteTests(pipeline._MarketTestBase):
    """A run that finds no competitor at all must say so, not report «تم»."""

    def test_zero_competitors_is_a_partial_answer_with_a_stated_reason(self):
        module = self.module
        empty_scan = {
            'reply': None,
            'parsed': {'competitors': [],
                       'notes': 'لم تُطابق مشاريع عقار المحاور المختارة'},
            'provider_error': '',
            'search_ran': True,
        }

        with self.app.app_context(), \
                patch.object(module, '_start_aqar_projects_scan',
                             return_value=None), \
                patch.object(module, '_await_aqar_projects_scan',
                             return_value=[]), \
                patch.object(module, '_start_source_plan_async',
                             return_value=None), \
                patch.object(module, '_run_scan_tasks',
                             return_value=[empty_scan]), \
                patch.object(module, '_run_parallel_expansions',
                             return_value=[]), \
                patch.object(module, '_verify_competitor_rows'), \
                patch.object(module, '_verify_market_urls',
                             return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos'):
            result = module._run_market_competitors({
                'city': 'جدة',
                'district': 'الاندلس',
                'competitorScope': {'mode': 'district', 'radius': '10'},
                'comparisonTypes': [{'type': 'residential', 'operation': 'sale'},
                                    {'type': 'commercial',
                                     'operation': ['sale', 'rent']}],
                'competitors': [],
                'mode': 'generate',
            })

        self.assertEqual(result.get('competitors'), [])
        self.assertTrue(result.get('partial'), result)
        # This synthetic payload detects as an English offer (same quirk the
        # hotel tests document), so the note follows the offer language.
        notes = result.get('notes') or ''
        self.assertTrue(
            'No matching competitors were found' in notes
            or 'لم يُعثر على منافسين مطابقين' in notes, notes)
        self.assertIn('الاندلس', notes)
