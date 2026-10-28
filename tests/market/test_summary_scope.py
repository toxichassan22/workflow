"""Market summary geography, scope rules and client controls."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import db  # noqa: E402
import market_study  # noqa: E402


def read_frontend_text(order):
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    parts.extend(path.read_text(encoding='utf-8')
                 for path in sorted((ROOT / 'assets' / 'css').rglob('*.css')))
    parts.extend((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8')
                 for name in order)
    return '\n'.join(parts)


class SummaryScopeModelTests(unittest.TestCase):

    def test_scope_canonical_shape_supports_whole_city_and_optional_districts(self):
        scope = market_study.normalize_summary_scope({
            'cities': [
                {'name': ' جدة ', 'districts': ['النرجس', '', 'الياسمين', 'النرجس']},
                {'name': 'جدة', 'districts': ['حي آخر']},
                {'name': 'مكة', 'districts': []},
            ]})
        self.assertEqual(scope, {'cities': [
            {'name': 'جدة', 'districts': ['النرجس', 'الياسمين']},
            {'name': 'مكة', 'districts': []},
        ]})

    def test_old_draft_uses_project_city_and_never_restores_distance(self):
        self.assertEqual(market_study.normalize_summary_scope(None, 'جدة'),
                         {'cities': [{'name': 'جدة', 'districts': []}]})
        self.assertEqual(market_study.normalize_summary_scope(
            {'mode': 'distance', 'distance': '10'}, 'جدة'),
            {'cities': [{'name': 'جدة', 'districts': []}]})

    def test_legacy_city_and_district_shapes_migrate_to_cities(self):
        self.assertEqual(market_study.normalize_summary_scope(
            {'mode': 'city', 'places': ['جدة', 'مكة']}),
            {'cities': [{'name': 'جدة', 'districts': []},
                        {'name': 'مكة', 'districts': []}]})
        self.assertEqual(market_study.normalize_summary_scope(
            {'mode': 'district', 'places': ['النرجس', 'الياسمين']}, 'جدة'),
            {'cities': [{'name': 'جدة', 'districts': ['النرجس', 'الياسمين']}]})

    def test_scope_caps_city_and_district_rows(self):
        many = market_study.normalize_summary_scope({
            'cities': [{'name': f'مدينة{i}', 'districts': [f'حي{n}' for n in range(30)]}
                       for i in range(30)]})
        self.assertEqual(len(many['cities']), market_study.SUMMARY_SCOPE_MAX_CITIES)
        self.assertEqual(len(many['cities'][0]['districts']),
                         market_study.SUMMARY_SCOPE_MAX_DISTRICTS_PER_CITY)


class SummaryScopePromptTests(unittest.TestCase):

    def test_city_scope_has_full_city_and_optional_district_rules(self):
        block = market_study._summary_scope_block({
            'summaryScope': {'cities': [
                {'name': 'جدة', 'districts': ['النرجس', 'الياسمين']},
                {'name': 'مكة', 'districts': []},
            ]}})
        self.assertIn('جدة', block)
        self.assertIn('النرجس', block)
        self.assertIn('مكة: كامل المدينة', block)
        self.assertIn('city_position يغطي المدينة كاملة دائمًا', block)
        self.assertIn('sector_performance وsupply وdemand', block)
        self.assertIn('نطاق المنافسين يخص جدول المنافسين فقط', block)
        self.assertNotIn('كم', block)

    def test_market_prompt_is_project_activity_scoped_and_evidence_only(self):
        prompt = market_study.build_summary_user_prompt(
            {'city': 'جدة', 'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
             'projectType': 'سكني', 'comparisonTypes': ['hotel']}, [])
        self.assertIn('الأنشطة والمكونات الاستثمارية المحددة: سكني', prompt)
        self.assertIn('لا تنشئ تحليلًا مستقلًا لقطاعات غير مختارة', prompt)
        self.assertNotIn('حلل السوق كله عبر السكني والتجاري والصناعي واللوجستي والفندقي', prompt)
        self.assertNotIn('السوق المحلي كاملًا لا فئة المشروع وحدها', prompt)
        self.assertIn('لا تبحث الآن ولا تستخدم معرفتك السابقة', prompt)
        self.assertIn('المنافسون، لمحور competition فقط', prompt)
        self.assertNotIn('بحث جوجل الأصلي', prompt)
        self.assertNotIn('حيين مجاورين مختلفين ممنوع', prompt)

    def test_market_prompt_template_file_is_respected(self):
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.txt', delete=False) as tf:
            tf.write("CUSTOM_MARKET_TEST_RULE: ركز فقط على العائد الاستثماري")
            tf_path = Path(tf.name)
        try:
            orig = getattr(market_study, '_MARKET_STUDY_PROMPT_FILE', None)
            setattr(market_study, '_MARKET_STUDY_PROMPT_FILE', tf_path)
            prompt = market_study.build_summary_user_prompt({'projectType': 'سكني'}, [])
            self.assertIn('CUSTOM_MARKET_TEST_RULE: ركز فقط على العائد الاستثماري', prompt)
        finally:
            if orig is not None:
                setattr(market_study, '_MARKET_STUDY_PROMPT_FILE', orig)
            if tf_path.exists():
                tf_path.unlink()

    def test_summary_activity_profile_ignores_competitor_comparison_types(self):
        profile = market_study.summary_activity_profile({
            'projectType': 'سكني', 'comparisonTypes': ['hotel', 'commercial']})
        self.assertIn('residential', profile['kinds'])
        self.assertNotIn('hospitality', profile['kinds'])
        self.assertNotIn('فندقي', profile['source_kinds'])
        self.assertEqual(profile['source_kinds'], ['سكني'])

    def test_market_prompt_surfaces_census_and_airport_indicators_with_limits(self):
        payload = {'summaryScope': {'cities': [
            {'name': 'جدة', 'districts': ['الروضة']}]} }
        prompt = market_study.build_summary_user_prompt(payload, [])
        self.assertIn('تعداد السعودية 2022', prompt)
        self.assertIn('عدد سكان المدينة والأسر في city_position', prompt)
        self.assertIn('كل حي مدخل منفصلًا', prompt)
        self.assertIn('حركة الرحلات الرسمية للمطار', prompt)
        self.assertIn('لا توزع حركة المطار على الأحياء', prompt)
        self.assertIn('احذف تفاصيل الحي غير المنشورة دون ذكر تعذر الوصول إليها', prompt)
        self.assertIn('للشقق المخدومة والشقق والفلل المعروضة للإقامة القصيرة', prompt)
        self.assertIn('إيجاراتها طويلة الأجل', prompt)
        self.assertIn('ثلاث منشآت قابلة للمقارنة على الأقل', prompt)
        self.assertIn('متوسطًا حسابيًا تقريبيًا لأسعار الغرف المعروضة', prompt)
        self.assertIn('اعرض المشاهدات دون متوسط', prompt)
        self.assertIn('لا تسمّه ADR تاريخيًا أو سنويًا', prompt)
        self.assertIn('لا تكتب كلمة «وسيط» في أي نص ظاهر للمستخدم', prompt)
        self.assertIn('أسقط قيمة المقياس الآخر بدل إعادة تسميتها متوسطًا', prompt)
        self.assertIn('متوسطًا حسابيًا تقريبيًا لأسعار الغرف', prompt)

        english = market_study.build_summary_user_prompt(
            {'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': ['Al Rawdah']}]}},
            [], offer_lang='en')
        self.assertIn('official Saudi Census 2022', english)
        self.assertIn('airport passenger and flight-movement figures', english)
        self.assertIn('never allocate airport traffic to districts', english)
        self.assertIn('Booking.com prices for bookable serviced apartments', english)
        self.assertIn('at least three comparable properties', english)
        self.assertIn('Keep it separate from official ADR', english)

    def test_market_prompt_attributes_uploaded_transactions_to_their_named_source(self):
        prompt = market_study.build_summary_user_prompt({
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
            'summaryLocalBenchmarks': {'groups': [{
                'sources': ['وزارة العدل'], 'deal_count_in_file': 3,
            }]},
        }, [])
        self.assertIn('سمّها «صفقات وزارة العدل»', prompt)
        self.assertIn('وزارة العدل', prompt)
        self.assertNotIn('مجهولة الهوية', prompt)

    def test_dynamic_district_and_rental_completeness_prompt_rules(self):
        prompt = market_study.build_summary_user_prompt({
            'city': 'جدة',
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
            'summaryLocalBenchmarks': {'groups': [{'district': 'العزيزية'}, {'district': 'الروضة'}]},
        }, [])
        self.assertIn('قاعدة تحليل الأحياء في الصفقات المرجعية (قاعدة ديناميكية وشاملة)', prompt)
        self.assertIn('يُمنع منعًا باتًا دمج أي حيين واردين في البيانات داخل فقرة واحدة', prompt)
        self.assertIn('أفرده بفقرة تحليلية مستقلة وكاملة', prompt)
        self.assertIn('قاعدة المؤشر الإيجاري لشبكة إيجار وسكني (شمولية القيمة والعدد)', prompt)
        self.assertIn('قاعدة شمولية كل الأحياء المدخلة في نطاق الدراسة', prompt)
        self.assertIn('دون استثناء أي حي', prompt)
        self.assertIn('تجنب تماماً أي تكرار ميكانيكي أو لفظي مثل «ريال سعودي سعوديًا»', prompt)
        self.assertIn('بل اسرد التحليل بفقرات متماسكة تبدأ بجمل افتتاحية استشارية متصلة', prompt)
        self.assertIn('قاعدة حظر أرقام الاستشهادات والأقواس المرجعية في المتن', prompt)

        en_prompt = market_study.build_summary_user_prompt({
            'city': 'Jeddah',
            'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': []}]},
        }, [], offer_lang='en')
        self.assertIn('Dynamic District Rule: For every district present in summaryLocalBenchmarks groups', en_prompt)
        self.assertIn('All Entered Districts Rule', en_prompt)
        self.assertIn('without omitting any entered district', en_prompt)
        self.assertIn('Rental Benchmark Rule: In rental_groups from Ejar and Sakani', en_prompt)
        self.assertIn('Avoid robotic colon-separated bullet headers', en_prompt)
        self.assertIn('No Citation Brackets Rule', en_prompt)

    def test_strip_citation_brackets_cleans_inline_footnote_references(self):
        text = 'وقد بلغ عدد الصفقات 47 صفقة[6] بمتوسط 9,434 ريال[1] وفق تقرير السوق.[15][16][17] كما بلغت القيمة 10 ملايين.[24, 25]'
        cleaned = market_study._strip_citation_brackets(text)
        self.assertEqual(cleaned, 'وقد بلغ عدد الصفقات 47 صفقة بمتوسط 9,434 ريال وفق تقرير السوق. كما بلغت القيمة 10 ملايين.')

        axis_cleaned = market_study._normalize_summary_axis_text(text)
        self.assertNotIn('[6]', axis_cleaned)
        self.assertNotIn('[1]', axis_cleaned)
        self.assertNotIn('[15]', axis_cleaned)
        self.assertNotIn('[24, 25]', axis_cleaned)

    def test_english_scope_and_research_prompt(self):
        block = market_study._summary_scope_block(
            {'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': ['Al Narjis']}]}}, 'en')
        self.assertIn('Jeddah', block)
        self.assertIn('city_position always covers the full city', block)
        prompt = market_study.build_summary_user_prompt(
            {'projectType': 'residential',
             'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': []}]}}, [], offer_lang='en')
        self.assertIn('Selected activities and revenue-bearing components: residential', prompt)
        self.assertNotIn('regardless of the client project type', prompt)
        self.assertNotIn('native Google search', prompt)

    def test_chat_research_prompt_uses_browser_search_and_city_scope(self):
        prompt = market_study.build_summary_chat_research_prompt(
            {'city': 'جدة', 'projectType': 'سكني', 'summaryScope': {'cities': [
                {'name': 'جدة', 'districts': ['النرجس']}]}},
            'demand', 'ابحث عن الطلب', [], {}, ['طلب الإيجار'])
        self.assertIn('SearXNG', prompt)
        self.assertIn('type_text', prompt)
        self.assertIn('النرجس', prompt)
        self.assertIn('الأنشطة والمكونات الاستثمارية المحددة: سكني', prompt)
        self.assertNotIn('بحث جوجل الأصلي', prompt)

    def test_summary_prompt_carries_the_binding_period(self):
        prompt = market_study.build_summary_user_prompt({
            'summaryPeriodBounds': {'from': '2023-01-01', 'to': '2026-01-01'},
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
        }, [])
        self.assertIn('فترة بيانات الملخص الملزمة', prompt)
        self.assertIn('2023-01-01', prompt)
        self.assertIn('2026-01-01', prompt)

    def test_project_brief_labels_summary_city_scope(self):
        block = market_study._project_input_block({
            'city': 'جدة', 'summaryScope': {
                'cities': [{'name': 'جدة', 'districts': ['النرجس']}]}})
        self.assertIn('نطاق ملخص السوق: جدة — الأحياء: النرجس', block)
        self.assertIn('نطاق المنافسين (لجدول المنافسين فقط)', block)

    def test_summary_prompt_pipeline_and_zonal_and_competitor_rules(self):
        prompt_ar = market_study.build_summary_user_prompt({
            'city': 'جدة',
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
        }, [])
        self.assertIn('قاعدة المعروض المستقبلي ومشاريع التطوير الكبرى (Future Pipeline)', prompt_ar)
        self.assertIn('قاعدة النطاقات السعرية الجغرافية المرجعية', prompt_ar)
        self.assertIn('قاعدة حجم السوق الكلي ومخزون الوحدات', prompt_ar)
        self.assertIn('حساب سعر المتر المربع الاسترشادي لوحدات المنافسين المباشرين', prompt_ar)
        self.assertIn('وظّف بيانات تفضيل نمط المسكن', prompt_ar)
        self.assertIn('تبنّ لغة استشارية تحليلية شجاعة وبناءة', prompt_ar)
        self.assertIn('قاعدة سلامة الأرقام والعملات والوحدات', prompt_ar)
        self.assertIn('قاعدة حظر مسمى «الملفات المرجعية» والنسبة الصريحة للجهات الرسمية', prompt_ar)
        self.assertIn('مؤشرات الهيئة العامة للعقار (REGA)', prompt_ar)

        prompt_en = market_study.build_summary_user_prompt({
            'city': 'Jeddah',
            'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': []}]},
        }, [], offer_lang='en')
        self.assertIn('Future Pipeline and Mega-Projects Rule', prompt_en)
        self.assertIn('Regional Price Benchmarks Rule', prompt_en)
        self.assertIn('Market Scale & Housing Stock Rule', prompt_en)
        self.assertIn('calculating the indicative price per square meter for direct competitor units', prompt_en)
        self.assertIn('Maintain an actionable real-estate advisory tone', prompt_en)
        self.assertIn('Number, Currency, and Unit Integrity Rule', prompt_en)
        self.assertIn('Official Authority Attribution Rule', prompt_en)
        self.assertIn('Real Estate General Authority (REGA) indicators', prompt_en)


class SummaryScopePayloadTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-scope.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_payload_normalizes_scope_and_reads_project_city(self):
        payload = self.application_module._prepare_market_payload({
            'projectData': {'city': 'جدة'},
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': ['النرجس']}]},
        }, tenant_id=None)
        self.assertEqual(payload['summaryScope']['cities'], [
            {'name': 'جدة', 'districts': ['النرجس']}])
        self.assertEqual(payload['city'], 'جدة')
        self.assertIn('summaryLocalBenchmarks', payload)

    def test_payload_without_scope_defaults_to_project_city(self):
        payload = self.application_module._prepare_market_payload(
            {'projectData': {'city': 'جدة'}}, tenant_id=None)
        self.assertEqual(payload['summaryScope'], {
            'cities': [{'name': 'جدة', 'districts': []}]})

    def test_summary_period_is_independent_from_the_competitor_period(self):
        payload = self.application_module._prepare_market_payload({
            'dataPeriod': '12m',
            'summaryPeriod': '3y',
        }, tenant_id=None)
        self.assertEqual(payload['summaryPeriodLabel'], 'آخر 3 سنوات')
        self.assertNotEqual(payload['summaryPeriodBounds'],
                            payload['dataPeriodBounds'])
        self.assertTrue(payload['summaryPeriodBounds'].get('from'))

    def test_old_drafts_without_a_summary_period_keep_the_shared_one(self):
        payload = self.application_module._prepare_market_payload({
            'dataPeriod': '24m',
        }, tenant_id=None)
        self.assertEqual(payload['summaryPeriodBounds'],
                         payload['dataPeriodBounds'])
        self.assertEqual(payload['summaryPeriodLabel'], 'آخر 24 شهرًا')

    def test_summary_research_depth_defaults_to_full_and_accepts_quick(self):
        module = self.application_module
        full = module._prepare_market_payload({}, tenant_id=None)
        self.assertEqual(full['summaryResearchDepth'], 'full')
        quick = module._prepare_market_payload(
            {'summaryResearchDepth': 'quick'}, tenant_id=None)
        self.assertEqual(quick['summaryResearchDepth'], 'quick')
        self.assertEqual(module.summary_research_depth({'summaryResearchDepth': 'سريع'}),
                         'quick')

    def test_quick_depth_keeps_the_top_sources_per_location(self):
        module = self.application_module
        group = {'key': 'g1'}
        jobs = [(group, [f'h{index}'], 'جدة', '') for index in range(10)]
        self.assertEqual(len(module.limit_summary_research_jobs(jobs, 'full')), 10)
        quick = module.limit_summary_research_jobs(jobs, 'quick')
        self.assertEqual(len(quick),
                         module.SUMMARY_RESEARCH_QUICK_HOSTS_PER_GROUP)
        self.assertEqual(quick[0][1], ['h0'])

    def test_quick_depth_caps_the_total_researcher_count(self):
        module = self.application_module
        jobs = [({'key': f'g{group}'}, ['h'], f'مدينة{city}', '')
                for city in range(20) for group in range(5)]
        quick = module.limit_summary_research_jobs(jobs, 'quick')
        self.assertLessEqual(len(quick),
                             module.SUMMARY_RESEARCH_QUICK_JOB_CAP)


class SummaryScopeFrontendTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-scope-fe.db')
        import app as application_module
        cls.frontend = read_frontend_text(application_module.FRONTEND_JS_ORDER)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_scope_controls_carry_city_and_optional_districts_without_distance(self):
        text = self.frontend
        self.assertIn('marketSummaryScopeCities', text)
        self.assertIn('data-summary-district-name', text)
        self.assertIn('addMarketSummaryScopeDistrict', text)
        self.assertIn('summary_scope', text)
        self.assertIn('addMarketSummaryScopeCity', text)
        self.assertNotIn('marketSummaryScopeDistance', text)
        self.assertNotIn('marketSummaryScopeMode', text)

    def test_scope_picker_is_inside_market_tab(self):
        text = self.frontend
        market_panel = text.index('id="marketMarketPanel" data-market-study-panel="market"')
        scope_at = text.index('id="marketSummaryScopeCities"')
        generate_at = text.index('marketGenerateSummaryBtn')
        self.assertGreater(scope_at, market_panel)
        self.assertLess(scope_at, generate_at)

    def test_scope_validation_requires_at_least_one_named_city(self):
        text = self.frontend
        self.assertIn('market.summary_scope_required', text)
        self.assertIn('scopeCheck.cities', text)
        self.assertIn('marketSummaryScopeAddCityBtn', text)

    def test_empty_scope_falls_back_to_the_project_city(self):
        text = self.frontend
        self.assertIn('function resolveMarketSummaryScope()', text)
        self.assertIn('const fallback = defaultMarketSummaryScope();', text)
        self.assertIn('resolveMarketSummaryScope()', text)

    def test_summary_has_its_own_period_control(self):
        text = self.frontend
        self.assertIn('id="marketSummaryPeriod"', text)
        self.assertIn('id="marketSummaryPeriodFrom"', text)
        self.assertIn('id="marketSummaryPeriodTo"', text)
        self.assertIn('summaryPeriod: state.summary_period', text)

    def test_summary_research_depth_control_is_wired(self):
        text = self.frontend
        self.assertIn('id="marketSummaryResearchDepth"', text)
        self.assertIn('summaryResearchDepth: state.summary_research_depth', text)
        self.assertIn('summary_research_depth', text)


if __name__ == '__main__':
    unittest.main()
