import copy
import unittest

import best_use_prices as prices
from best_use_contract import ProposalError


class PriceEvidenceTests(unittest.TestCase):
    def observation(self, value=5000, identity='101', mode='sale', city='جدة', district='حي الاختبار', published='2026-09-01'):
        operation = 'للبيع' if mode == 'sale' else 'للإيجار السنوي'
        excerpt = f'شقق سكنية {operation} في {city} {district} بسعر {value} ريال سعودي للمتر المربع. رقم الإعلان: {identity}. نشر: {published}'
        url = 'https://example.test/listing/' + identity
        return {'use': 'residential', 'revenueMode': mode, 'value': value, 'currency': 'SAR', 'unit': 'sqm',
                'period': 'oneOff' if mode == 'sale' else 'year', 'city': city, 'district': district,
                'url': url, 'excerpt': excerpt, 'publishedAt': published, 'propertyId': identity}

    def scan(self, rows, **kwargs):
        content = {}
        for row in rows:
            content[row['url']] = content.get(row['url'], '') + '\n' + row['excerpt']
        pages = [{'url': url, 'content': excerpt} for url, excerpt in content.items()]
        return prices.build_scan(['residential'], rows, pages, '2026-10-12T10:00:00', 'جدة', 'حي الاختبار', **kwargs)

    def test_one_listing_is_not_an_average(self):
        scan = self.scan([self.observation()])
        self.assertIsNone(scan['table'][0]['salePerSqm'])
        self.assertEqual(scan['table'][0]['metrics']['sale']['count'], 1)
        self.assertEqual(scan['observations'][0]['observationKind'], 'listing')

    def test_three_independent_homogeneous_observations_have_a_server_average(self):
        scan = self.scan([self.observation(value, str(index)) for index, value in enumerate((4000, 5000, 6000), 1)])
        metric = scan['table'][0]['metrics']['sale']
        self.assertEqual(metric['value'], 5000)
        self.assertEqual(metric['count'], 3)
        self.assertEqual(metric['method'], 'arithmetic_mean')
        self.assertEqual((metric['min'], metric['max']), (4000, 6000))

    def test_duplicated_listing_across_urls_does_not_inflate_the_count(self):
        row = self.observation()
        duplicate = dict(row, url='https://other.test/ads/101')
        scan = self.scan([row, duplicate, dict(row, url=row['url'] + '?utm_source=test')])
        self.assertEqual(len(scan['observations']), 1)
        self.assertIsNone(scan['table'][0]['salePerSqm'])

    def test_other_district_and_city_are_retained_with_their_real_scope_not_averaged_locally(self):
        rows = [self.observation(identity=str(index), city='الرياض', district='حي آخر') for index in range(3)]
        scan = self.scan(rows)
        self.assertIsNone(scan['table'][0]['salePerSqm'])
        self.assertTrue(all(row['city'] == 'الرياض' and row['district'] == 'حي آخر' for row in scan['observations']))

    def test_links_without_retrieved_evidence_and_homepages_are_not_proof(self):
        row = self.observation()
        for pages in ([], [{'url': row['url'], 'content': 'سكني للبيع في جدة'}]):
            with self.subTest(pages=pages), self.assertRaises(ProposalError):
                prices.verify_observation(row, pages, '2026-10-12T10:00:00')
        row['url'] = 'https://example.test/'
        with self.assertRaises(ProposalError):
            prices.verify_observation(row, [{'url': row['url'], 'content': row['excerpt']}], '2026-10-12T10:00:00')

    def test_value_currency_unit_and_period_are_bound_to_the_original_excerpt(self):
        row = self.observation(mode='rent')
        pages = [{'url': row['url'], 'content': row['excerpt']}]
        for changes in ({'value': 9000}, {'currency': 'USD'}, {'unit': 'unit'}, {'period': 'month'}, {'use': 'hospitality'}):
            with self.subTest(changes=changes), self.assertRaises(ProposalError):
                prices.verify_observation(dict(row, **changes), pages, '2026-10-12T10:00:00')

    def test_missing_publication_date_is_not_replaced_by_retrieval_date(self):
        rows = [self.observation(identity=str(index), published='') for index in range(3)]
        scan = self.scan(rows)
        self.assertIsNone(scan['table'][0]['salePerSqm'])
        self.assertTrue(all(item['publishedAt'] is None and item['freshnessStatus'] == 'unknown' for item in scan['observations']))

    def test_old_or_future_observations_are_not_comparable(self):
        for published in ('2025-01-01', '2027-01-01'):
            with self.subTest(published=published):
                scan = self.scan([self.observation(identity=str(index), published=published) for index in range(3)])
                self.assertIsNone(scan['table'][0]['salePerSqm'])

    def test_a_search_that_did_not_run_is_not_a_successful_empty_scan(self):
        with self.assertRaises(ProposalError):
            self.scan([], search_ran=False)

    def test_sale_and_rent_can_be_observed_for_the_same_property_without_mixing(self):
        rows = [self.observation(identity=str(index), mode=mode, value=5000 if mode == 'sale' else 400)
                for index in range(3) for mode in ('sale', 'rent')]
        scan = self.scan(rows)
        self.assertEqual(len(scan['observations']), 6)
        self.assertEqual(scan['table'][0]['salePerSqm'], 5000)
        self.assertEqual(scan['table'][0]['rentPerSqmYear'], 400)

    def test_revenue_potential_uses_net_area_and_never_claims_roi(self):
        scan = self.scan([self.observation(identity=str(index)) for index in range(3)])
        components = [{'name': 'شقق', 'useType': 'residential', 'investmentModel': 'sale',
                       'builtArea': 1000, 'revenueArea': 800, 'revenueAreaBasis': 'افتراض مساحة تخطيطي'}]
        result = prices.revenue_potential(components, scan)
        self.assertEqual(result['value'], 4000000)
        self.assertEqual(result['metric'], 'revenue_potential')
        self.assertTrue(result['excludesCostsAndROI'])
        self.assertEqual(result['areaStatus'], 'planning_assumption')
        components[0].pop('revenueAreaBasis')
        self.assertIsNone(prices.revenue_potential(components, scan)['value'])

    def test_mixed_sale_and_annual_rent_have_no_aggregate_financial_rank(self):
        rows = [self.observation(identity=str(index), mode=mode, value=5000 if mode == 'sale' else 400)
                for index in range(3) for mode in ('sale', 'rent')]
        scan = self.scan(rows)
        components = [{'name': mode, 'useType': 'residential', 'investmentModel': mode,
                       'revenueArea': 800, 'revenueAreaBasis': 'افتراض صافي مساحة'} for mode in ('sale', 'annualRent')]
        result = prices.revenue_potential(components, scan)
        self.assertIsNone(result['value'])
        self.assertEqual(result['comparisonStatus'], 'mixed_basis')
        self.assertIsNone(result['rank'])

    def test_only_homogeneous_complete_concepts_are_ranked(self):
        metric = {'currency': 'SAR', 'revenueMode': 'sale', 'period': 'oneOff', 'comparisonStatus': 'comparable', 'rank': None}
        concepts = [{'id': 'a', 'revenuePotential': dict(metric, value=100)},
                    {'id': 'b', 'revenuePotential': dict(metric, value=200)},
                    {'id': 'c', 'revenuePotential': dict(metric, value=300, revenueMode='rent', period='year')},
                    {'id': 'd', 'revenuePotential': dict(metric, value=None, comparisonStatus='insufficient_data')}]
        prices.rank_concepts(concepts)
        self.assertEqual(concepts[0]['revenuePotential']['rank'], 2)
        self.assertEqual(concepts[1]['revenuePotential']['rank'], 1)
        self.assertIsNone(concepts[2]['revenuePotential']['rank'])
        self.assertIsNone(concepts[3]['revenuePotential']['rank'])


if __name__ == '__main__':
    unittest.main()
