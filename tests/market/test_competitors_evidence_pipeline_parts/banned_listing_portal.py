import time
from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline

browser = pipeline.browser
evidence = pipeline.evidence
market_study = pipeline.market_study
_FakeWorker = pipeline._FakeWorker
_ROW = pipeline._ROW
_LISTING_PAGE = pipeline._LISTING_PAGE
_agent_reply = pipeline._agent_reply

class BannedListingPortalTests(pipeline._MarketTestBase):
    """Owner rule: aqar.fm is the only classifieds portal on a competitor
    row — Booking.com is allowed for hotel-operation rows alone. Every other
    portal is banned at every layer: the deterministic search never opens
    it, absorbed citations drop it, the price fill ignores it, and the
    finalizer strips it (plus any price it alone carried)."""

    def test_banned_host_matrix(self):
        cases = (
            ('https://sa.aqar.fm/listing/1', 'إيجار', False),
            ('https://aqar.fm/x', 'بيع', False),
            ('https://developer.sa/projects/x', 'إيجار', False),
            ('https://sakani.sa/reports-and-data', 'إيجار', False),
            ('https://bayut.sa/listing/1', 'إيجار', True),
            ('https://www.wasalt.sa/p/1', 'بيع', True),
            ('https://dealapp.sa/x', 'إيجار', True),
            ('https://dubizzle.sa/x', 'إيجار', True),
            ('https://booking.com/hotel', 'تشغيل فندقي', False),
            ('https://booking.com/hotel', 'بيع', True),
            ('https://airbnb.com/rooms/1', 'تشغيل فندقي', True),
            ('https://trivago.sa/hotel', 'تشغيل فندقي', True),
            ('https://trivago.sa/x', 'إيجار', True),
            ('https://trivago.sa/x', 'بيع', True),
            ('https://instagram.com/p/abc', 'بيع', True),
            ('https://www.instagram.com/hotel.page/', 'تشغيل فندقي', True),
            ('https://m.facebook.com/page', 'إيجار', True),
            ('https://tiktok.com/@x/video/1', 'بيع', True),
            ('https://x.com/status/1', 'بيع', True),
            ('https://t.co/abc', 'إيجار', True),
            ('https://youtube.com/watch?v=1', 'بيع', True),
            ('https://wa.me/966500000000', 'بيع', True),
            ('https://linkedin.com/company/x', 'بيع', True),
            # Domain-boundary tokens must not swallow lookalike hosts.
            ('https://www.fox.com/show', 'بيع', False),
            ('https://alt.co/page', 'إيجار', False),
        )
        for url, operation, expected in cases:
            self.assertEqual(
                market_study.banned_competitor_listing_host(url, operation),
                expected, f'{url} / {operation}')

    def test_deterministic_search_never_opens_banned_hits(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)
        opened = []

        def fake_search(query, max_results=8, **_kw):
            return [
                {'title': 'نتيجة محظورة', 'url': 'https://bayut.sa/p/1',
                 'snippet': ''},
                {'title': _LISTING_PAGE['title'], 'url': _LISTING_PAGE['url'],
                 'snippet': 'إعلان'},
            ]

        def fake_open(url, **_kw):
            opened.append(url)
            if url == _LISTING_PAGE['url']:
                return {'url': url, 'final_url': url,
                        'title': _LISTING_PAGE['title'],
                        'text': _LISTING_PAGE['content'], 'error': None}
            return {'url': url, 'final_url': url, 'title': '', 'text': '',
                    'error': 'timeout'}

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('aqar evidence is enough')), \
                patch.object(browser, 'thread_local_browser',
                             lambda *a, **kw: _FakeWorker()), \
                patch.object(browser, 'web_search', side_effect=fake_search), \
                patch.object(browser, 'open_url', side_effect=fake_open):
            module._verify_competitor_rows(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300)

        self.assertEqual(opened, [_LISTING_PAGE['url']])
        self.assertIsNone(pool.get_page('https://bayut.sa/p/1'))
        self.assertEqual(row.get('verify_state'), 'verified')

    def test_absorb_drops_banned_citation_pages(self):
        module = self.module
        row = dict(_ROW)
        matched_pages = {}
        response = _agent_reply(
            [], ['https://bayut.sa/listing/marqaa'],
            title='إعلان برج مرقاة النرجس',
            content='وحدات مشروع مرقاة النرجس — السعر 850,000 ريال')
        matched, official = module._absorb_verify_response(
            row, response, {'مرقاة', 'النرجس'}, 2, matched_pages)
        self.assertEqual(matched, [])
        self.assertEqual(official, '')
        self.assertFalse(row.get('price_value'))

    def test_pool_page_on_banned_host_cannot_verify(self):
        module = self.module
        pool = evidence.EvidencePool()
        pool.add_page('https://bayut.sa/listing/marqaa',
                      title='إعلان برج مرقاة النرجس',
                      content='برج مرقاة النرجس — السعر 850,000 ريال')
        row = dict(_ROW)
        with self.app.app_context():
            self.assertFalse(
                module._verify_row_from_pool(row, {'city': 'الرياض'}, {}, pool))
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('source_urls'))

    def test_attach_retrieved_citations_skips_banned_pages(self):
        module = self.module
        row = dict(_ROW)
        pages = [
            {'url': 'https://bayut.sa/listing/marqaa',
             'title': 'إعلان برج مرقاة النرجس', 'content': 'مرقاة النرجس'},
            {'url': 'https://almemar.sa/marqaa-narjis',
             'title': 'مشروع برج مرقاة النرجس', 'content': 'مرقاة النرجس'},
        ]
        with self.app.app_context():
            module._attach_retrieved_citations([row], pages)
        self.assertEqual(row.get('source_urls'),
                         ['https://almemar.sa/marqaa-narjis'])

    def test_verified_price_url_on_banned_host_is_rejected(self):
        module = self.module
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع'}
        module._apply_verified_competitor_price(
            row,
            {'price': {'type': 'سعر الوحدة', 'value': '850000',
                       'url': 'https://bayut.sa/p/1'}},
            {'https://bayut.sa/p/1'})
        self.assertFalse(row.get('price_value'))

    def test_shared_index_page_stamps_no_price_on_any_row(self):
        """Regression — one portal index page naming many projects used to
        stamp the same page-wide price median on every competitor row it
        matched. Only a page that names the project in its title or URL may
        yield that row's price; rows without one stay empty."""
        module = self.module
        pool = evidence.EvidencePool()
        pool.add_page('https://sa.aqar.fm/jeddah/all',
                      title='كل مشاريع جدة',
                      content='برج مرقاة النرجس ومجمع الواجهة — 9,273 ريال '
                              '— 150,000 ريال سنوياً — 88,000 ريال')
        rows = [dict(_ROW), {'name': 'مجمع الواجهة', 'operation_type': 'إيجار'}]
        with self.app.app_context():
            for row in rows:
                module._verify_row_from_pool(row, {'city': 'جدة'}, {}, pool)
        for row in rows:
            self.assertEqual(row.get('verify_state'), 'verified')
            self.assertFalse(row.get('price_value'))
            self.assertFalse(row.get('price_listed'))

    def test_project_named_page_still_yields_its_own_price(self):
        module = self.module
        pool = evidence.EvidencePool()
        pool.add_page('https://akhbar.sa/marqaa-prices',
                      title='برج مرقاة النرجس — أسعار الوحدات',
                      content='برج مرقاة النرجس — سعر الوحدة 850,000 ريال')
        row = dict(_ROW)
        with self.app.app_context():
            self.assertTrue(module._verify_row_from_pool(
                row, {'city': 'الرياض'}, {}, pool))
        self.assertEqual(row.get('price_value'), '850000')

    def test_price_fill_ignores_banned_and_unnamed_pages(self):
        module = self.module
        pages = [
            {'url': 'https://bayut.sa/x', 'title': 'إعلان برج مرقاة النرجس',
             'content': 'سعر 850,000 ريال'},
            {'url': 'https://sa.aqar.fm/jeddah', 'title': 'كل إعلانات جدة',
             'content': 'برج مرقاة النرجس مذكور — إيجار 9,273 ريال'},
        ]
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_urls': [page['url'] for page in pages]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=AssertionError(
                                 'no fetch — content is inlined')):
            filled = module._fill_competitor_price_from_listings(
                row, [page['url'] for page in pages], pages=pages)
        self.assertFalse(filled)
        self.assertFalse(row.get('price_value'))

    def test_undeclared_jsonld_price_is_not_a_sar_price(self):
        """A bare "price": N with no declared unit is a number, not a price —
        offer internals, ids and points serialize the same way, and the old
        default-SAR read stamped them onto the row."""
        module = self.module
        page = {'url': 'https://marriott.example/hotel/assila',
                'title': 'فندق أصيلة جدة — الغرف والأجنحة',
                'content': ('فندق أصيلة جدة — أجنحة فاخرة '
                            '{"@type":"Offer","price":999,"stars":5}')}
        row = {'name': 'فندق أصيلة', 'operation_type': 'تشغيل فندقي',
               'source_urls': [page['url']]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=AssertionError('content is inlined')):
            filled = module._fill_competitor_price_from_listings(
                row, [page['url']], pages=[page])
        self.assertFalse(filled)
        self.assertFalse(row.get('price_value'))

    def test_listing_price_converts_declared_usd_to_sar(self):
        """A project-named page quoting USD converts at the fixed peg — the
        ر.س cell holds riyals, the printed dollar figure stays in the cache."""
        module = self.module
        page = {'url': 'https://marriott.example/hotel/assila',
                'title': 'فندق أصيلة جدة — الغرف والأجنحة',
                'content': ('فندق أصيلة جدة — سعر الليلة '
                            '{"@type":"Offer","price":"1000",'
                            '"priceCurrency":"USD"}')}
        row = {'name': 'فندق أصيلة', 'operation_type': 'تشغيل فندقي',
               'source_urls': [page['url']]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=AssertionError('content is inlined')), \
                patch.object(market_study, '_live_fx_rates', return_value={}):
            filled = module._fill_competitor_price_from_listings(
                row, [page['url']], pages=[page])
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '3750')   # 1,000 USD × 3.75
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_cache']['original_price_value'], '1000')
        self.assertEqual(row['price_cache']['original_currency'], 'USD')
        self.assertIn('USD', row.get('note') or '')

    def test_listing_prices_detect_jod_and_egp_mentions(self):
        """The currency-word pattern is not a USD/EUR club — Jordanian dinar
        and Egyptian-pound mentions resolve through the alias table."""
        module = self.module
        html = ('شاليه مفروش 500 دينار أردني لليلة' + ('x' * 200) +
                'غرفة فندقية 1,200 ج.م في الليلة')
        with patch.object(market_study, '_live_fx_rates', return_value={}):
            found = {(item['value'], item['currency'])
                     for item in module._extract_listing_prices(html)}
        self.assertIn((500.0, 'JOD'), found)
        self.assertIn((1200.0, 'EGP'), found)

    def test_fill_competitor_price_converts_jod_to_sar(self):
        module = self.module
        page = {'url': 'https://chalets.example/omar',
                'title': 'شاليه عمر — الحجز',
                'content': 'شاليه عمر للحجز اليومي 200 دينار أردني'}
        row = {'name': 'شاليه عمر', 'operation_type': 'تشغيل فندقي',
               'source_urls': [page['url']]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=AssertionError('content is inlined')), \
                patch.object(market_study, '_live_fx_rates', return_value={}):
            filled = module._fill_competitor_price_from_listings(
                row, [page['url']], pages=[page])
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '1058')   # 200 JOD × 5.29
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_cache']['original_price_value'], '200')
        self.assertEqual(row['price_cache']['original_currency'], 'JOD')

    def test_listing_prices_drop_currency_without_any_rate(self):
        """An ISO-looking token with no rate anywhere is not a currency the
        cell can express — the mention dies at extraction."""
        module = self.module
        html = 'مساحة المشروع 1,500 SQM إجمالية'
        with patch.object(market_study, '_live_fx_rates', return_value={}):
            self.assertEqual(module._extract_listing_prices(html), [])

    def test_instagram_source_yields_no_price_and_no_source(self):
        """The cited instagram URL is refused before a price lands — a reel
        caption is not evidence."""
        module = self.module
        row = {'name': 'فندق اختبار', 'operation_type': 'تشغيل فندقي',
               'source_urls': ['https://instagram.com/hotel.test']}
        module._apply_verified_competitor_price(
            row,
            {'price': {'type': 'سعر الليلة', 'value': '900', 'currency': 'SAR',
                       'url': 'https://instagram.com/hotel.test'}},
            {'https://instagram.com/hotel.test'})
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('price_currency'))
        self.assertFalse(row.get('field_sources'))
        module._drop_banned_competitor_listing_urls(row)
        self.assertFalse(row.get('source_urls'))

    def test_drop_banned_listing_urls_strips_row_and_clears_price(self):
        module = self.module
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_url': 'https://bayut.sa/p/1',
               'source_urls': ['https://bayut.sa/p/1',
                               'https://almemar.sa/marqaa'],
               'price_value': '850000', 'price_listed': True,
               'price_cache': {'price_value': '850000'},
               'field_sources': {'price_value': ['https://bayut.sa/p/1'],
                                 'name': ['https://almemar.sa/marqaa']}}
        module._drop_banned_competitor_listing_urls(row)
        self.assertEqual(row['source_urls'], ['https://almemar.sa/marqaa'])
        self.assertEqual(row['source_url'], 'https://almemar.sa/marqaa')
        # The figure stood on the banned link alone — back to empty.
        self.assertFalse(row.get('price_value'))
        self.assertNotIn('price_cache', row)
        self.assertNotIn('price_listed', row)
        # A price kept beside an allowed source survives the purge.
        row2 = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
                'price_value': '850000',
                'field_sources': {'price_value': ['https://sa.aqar.fm/l/1',
                                                  'https://bayut.sa/p/1']}}
        module._drop_banned_competitor_listing_urls(row2)
        self.assertEqual(row2['price_value'], '850000')
        self.assertEqual(row2['field_sources']['price_value'],
                         ['https://sa.aqar.fm/l/1'])

    def test_competitor_prompt_bans_non_aqar_listings(self):
        prompt = market_study.build_competitors_user_prompt(
            {'projectType': 'سكني', 'city': 'جدة',
             'components': [{'name': 'الشقق', 'useType': 'residential',
                             'investmentModel': 'sale'}]},
            [], offer_lang='ar')
        self.assertIn('sa.aqar.fm', prompt)
        self.assertIn('bayut.sa', prompt)
        self.assertIn('Booking.com', prompt)
