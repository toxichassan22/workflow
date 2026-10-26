from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline


def _booking_hotel_row(index):
    """A row the Booking fill wrote: priced, sourced — and without a district."""
    url = f'https://www.booking.com/hotel/sa/test-hotel-{index}.html'
    return {
        'name': f'فندق الاختبار {index}',
        'project_type': 'فندقي',
        'operation_type': 'تشغيل فندقي',
        'hotel_stars': '4',
        'classification': 'مباشر',
        'status': 'قائم',
        'price_type': 'نطاق أسعار الغرف',
        'price_from': '500',
        'price_to': '700',
        'price_currency': 'SAR',
        'source': 'Booking.com',
        'source_url': url,
        'source_urls': [url],
        'row_source': 'booking',
        'verify_state': 'verified',
    }


class HotelEmptyRegenerationTests(pipeline._MarketTestBase):
    """Generating hotels must never turn a filled table into an empty one.

    Booking ignores the neighbourhood filter on some days; the scans then
    return no rows while the table already holds the hotel rows completed
    earlier. The scope filter used to run over the merged list and drop those
    rows — they carry no district — so the client's table came back empty from
    a run that had discovered nothing.
    """

    def test_existing_hotel_rows_survive_a_run_that_finds_nothing(self):
        module = self.module
        existing = [_booking_hotel_row(index) for index in range(9)]
        empty_scan = {
            'reply': None,
            'parsed': {'competitors': [],
                       'notes': 'تعذّر فتح نتائج فلتر الحي على Booking'},
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
                'comparisonTypes': [{'type': 'hotel', 'operation': [],
                                     'stars': ['4', '5']}],
                'competitors': existing,
                'mode': 'generate',
            })

        names = [row.get('name') for row in result.get('competitors') or []]
        self.assertEqual(len(names), 9, result.get('notes'))
        self.assertEqual(names, [row['name'] for row in existing])
        # Nothing new was discovered, so the run is a partial answer — never a
        # clean «تم» over a table this run did not refresh.
        self.assertTrue(result.get('partial'), result)
        self.assertIn('أُبقيت الصفوف الحالية', result.get('notes') or '')
