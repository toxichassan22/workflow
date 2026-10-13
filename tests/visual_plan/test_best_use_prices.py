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

    def test_grounded_answer_text_is_itself_evidence_for_an_overview(self):
        row = self.observation()
        # Google AI Mode answers in synthesized sentences, not listing excerpts —
        # the answer's own sentence is the evidence, so the row verifies as an
        # 'overview' observation even when no page carried it verbatim.
        for pages in ([], [{'url': row['url'], 'content': 'سكني للبيع في جدة'}]):
            with self.subTest(pages=pages):
                verified = prices.verify_observation(row, pages, '2026-10-12T10:00:00')
                self.assertEqual(verified['observationKind'], 'overview')
        row['url'] = 'https://example.test/'
        verified = prices.verify_observation(row, [], '2026-10-12T10:00:00')
        self.assertEqual(verified['observationKind'], 'overview')
        self.assertEqual(verified['url'], '')
        for excerpt in ('الأسعار تختلف حسب الموقع', ''):
            with self.subTest(excerpt=excerpt), self.assertRaises(ProposalError):
                prices.verify_observation(dict(row, excerpt=excerpt), [], '2026-10-12T10:00:00')

    def test_an_overview_average_is_evidence_while_a_listing_average_is_not(self):
        row = self.observation()
        row['excerpt'] = ('متوسط سعر المتر للشقق السكنية المعروضة للبيع في جدة حي الاختبار '
                          'يبلغ 5000 ريال سعودي للمتر المربع. نشر: 2026-09-01')
        verified = prices.verify_observation(row, [], '2026-10-12T10:00:00')
        self.assertEqual(verified['observationKind'], 'overview')
        self.assertEqual(verified['value'], 5000)
        # The same sentence quoted verbatim from the cited page is a listing
        # claim — and a page carrying an average is no individual observation.
        with self.assertRaises(ProposalError):
            prices.verify_observation(row, [{'url': row['url'], 'content': row['excerpt']}],
                                      '2026-10-12T10:00:00')

    def test_district_rates_thousands_url_taxonomy_and_riyal_glyphs_are_evidence(self):
        base = dict(self.observation(), propertyId='', publishedAt=None)
        # A district-level sqm rate names no use or operation — nothing in the
        # sentence contradicts the residential-sale claim («وسيط سعر المتر …»).
        row = dict(base, value=4899,
                   excerpt='وسيط سعر المتر المربع في جدة حي الاختبار هو ٤٬٨٩٩ ريال سعودي/م².')
        self.assertEqual(prices.verify_observation(row, [], '2026-10-12T10:00:00')['value'], 4899)
        # …but a rate that names a different use still contradicts the claim.
        with self.assertRaises(ProposalError):
            prices.verify_observation(
                dict(row, excerpt='وسيط سعر المتر للمكاتب في جدة حي الاختبار هو ٤٬٨٩٩ ريال/م².'),
                [], '2026-10-12T10:00:00')
        # Thousand-word values bind («28 ألف ريال سنويًا» → 28000), and a
        # periodic non-sqm price is rent evidence without an explicit إيجار.
        row = dict(base, revenueMode='rent', unit='unit', period='year', value=28000,
                   excerpt='أسعار شقق مفروشة في جدة حي الاختبار تبدأ من 28 ألف ريال سعودي سنويًا.')
        self.assertEqual(prices.verify_observation(row, [], '2026-10-12T10:00:00')['use'], 'residential')
        row['use'] = 'hospitality'  # furnished apartments read as hospitality too
        self.assertEqual(prices.verify_observation(row, [], '2026-10-12T10:00:00')['use'], 'hospitality')
        # The listing URL carries the portal's own taxonomy: «/شقق-للإيجار/» proves rent.
        row = dict(base, revenueMode='rent', unit='unit', period='year', value=65000,
                   url='https://aqar.fm/%D8%B4%D9%82%D9%82-%D9%84%D9%84%D8%A5%D9%8A%D8%AC%D8%A7%D8%B1/%D8%AC%D8%AF%D8%A9',
                   excerpt='65,000 ريال/سنوي شقة في جدة حي الاختبار')
        self.assertEqual(prices.verify_observation(row, [], '2026-10-12T10:00:00')['revenueMode'], 'rent')
        # The riyal glyph on Saudi hosts counts as SAR; on other domains it does not.
        row = dict(base, use='retail', revenueMode='rent', unit='unit', period='year', value=200000,
                   url='https://sa.aqar.fm/%D9%85%D8%AD%D9%84%D8%A7%D8%AA-%D9%84%D9%84%D8%A5%D9%8A%D8%AC%D8%A7%D8%B1/x',
                   excerpt='محل تجاري في جدة حي الاختبار 200,000 §/سنوي150م²')
        self.assertEqual(prices.verify_observation(row, [], '2026-10-12T10:00:00')['use'], 'retail')
        with self.assertRaises(ProposalError):
            prices.verify_observation(dict(row, url='https://ae.example.com/shops-for-rent/x'),
                                      [], '2026-10-12T10:00:00')

    def test_a_single_grounded_overview_fills_a_preliminary_scan(self):
        row = self.observation()
        row['url'] = ''
        row['excerpt'] = ('متوسط سعر المتر للشقق السكنية المعروضة للبيع في جدة حي الاختبار '
                          'يبلغ 5000 ريال سعودي للمتر المربع.')
        row['publishedAt'] = None
        row['propertyId'] = ''
        scan = self.scan([row], preliminary=True)
        self.assertEqual(scan['table'][0]['salePerSqm'], 5000)
        self.assertEqual(scan['observations'][0]['observationKind'], 'overview')

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
