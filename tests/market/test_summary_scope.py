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

    def test_market_prompt_is_market_wide_and_evidence_only(self):
        prompt = market_study.build_summary_user_prompt(
            {'city': 'جدة', 'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
             'projectType': 'سكني'}, [])
        self.assertIn('حلل السوق كله عبر السكني والتجاري والصناعي واللوجستي والفندقي', prompt)
        self.assertIn('لا تبحث الآن ولا تستخدم معرفتك السابقة', prompt)
        self.assertIn('المنافسون، لمحور competition فقط', prompt)
        self.assertNotIn('بحث جوجل الأصلي', prompt)
        self.assertNotIn('حيين مجاورين مختلفين ممنوع', prompt)

    def test_english_scope_and_research_prompt(self):
        block = market_study._summary_scope_block(
            {'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': ['Al Narjis']}]}}, 'en')
        self.assertIn('Jeddah', block)
        self.assertIn('city_position always covers the full city', block)
        prompt = market_study.build_summary_user_prompt(
            {'summaryScope': {'cities': [{'name': 'Jeddah', 'districts': []}]}}, [], offer_lang='en')
        self.assertIn('regardless of the client project type', prompt)
        self.assertNotIn('native Google search', prompt)

    def test_chat_research_prompt_uses_browser_search_and_city_scope(self):
        prompt = market_study.build_summary_chat_research_prompt(
            {'city': 'جدة', 'summaryScope': {'cities': [
                {'name': 'جدة', 'districts': ['النرجس']}]}},
            'demand', 'ابحث عن الطلب', [], {}, ['طلب الإيجار'])
        self.assertIn('SearXNG', prompt)
        self.assertIn('type_text', prompt)
        self.assertIn('النرجس', prompt)
        self.assertNotIn('بحث جوجل الأصلي', prompt)

    def test_project_brief_labels_summary_city_scope(self):
        block = market_study._project_input_block({
            'city': 'جدة', 'summaryScope': {
                'cities': [{'name': 'جدة', 'districts': ['النرجس']}]}})
        self.assertIn('نطاق ملخص السوق: جدة — الأحياء: النرجس', block)
        self.assertIn('نطاق المنافسين (لجدول المنافسين فقط)', block)


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


if __name__ == '__main__':
    unittest.main()
