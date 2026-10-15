"""Summary scope: the market summary's own geographic frame.

The summary used to inherit exactly one frame — the entered district plus the
competitors radius, with a single nearest-district substitute. It now carries
its own ``summary_scope`` setting, independent of the competitors table:

- ``distance`` (default): the historical behaviour, byte for byte — old
  drafts without the field generate exactly as before.
- ``city`` / ``district``: the analysis binds to a user-entered place list
  instead, with the same listed-only discipline and no invented substitutes.

Run like every other suite, one suite per process::

    python -m unittest tests.market.test_summary_scope
"""

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
    """The full client source: shell + styles + scripts in load order."""
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    for _css in sorted((ROOT / 'assets' / 'css').rglob('*.css')):
        parts.append(_css.read_text(encoding='utf-8'))
    for name in order:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


class SummaryScopeModelTests(unittest.TestCase):

    def test_absent_scope_is_historical_distance(self):
        scope = market_study.normalize_summary_scope(None)
        self.assertEqual(scope['mode'], 'distance')
        self.assertEqual(scope['distance'], '10')
        self.assertEqual(scope['places'], [])

    def test_unknown_mode_falls_back_to_distance(self):
        scope = market_study.normalize_summary_scope(
            {'mode': 'country', 'places': ['الرياض']})
        self.assertEqual(scope['mode'], 'distance')

    def test_listed_mode_keeps_clean_places(self):
        scope = market_study.normalize_summary_scope({
            'mode': 'city', 'places': [' جدة ', '', 'مكة', 'جدة']})
        self.assertEqual(scope['mode'], 'city')
        self.assertEqual(scope['places'], ['جدة', 'مكة'])

    def test_listed_mode_without_names_falls_back(self):
        # A scope with no names cannot bind any figure — behave as before.
        scope = market_study.normalize_summary_scope(
            {'mode': 'district', 'places': []})
        self.assertEqual(scope['mode'], 'distance')

    def test_places_cap_and_string_shape(self):
        scope = market_study.normalize_summary_scope(
            {'mode': 'district',
             'places': 'النرجس، الياسمين\nالعليا'})
        self.assertEqual(scope['places'], ['النرجس', 'الياسمين', 'العليا'])
        many = market_study.normalize_summary_scope(
            {'mode': 'city', 'places': [f'مدينة{i}' for i in range(30)]})
        self.assertEqual(len(many['places']),
                         market_study.SUMMARY_SCOPE_MAX_PLACES)

    def test_distance_values_mirror_radius_options(self):
        scope = market_study.normalize_summary_scope(
            {'mode': 'distance', 'distance': 'custom',
             'distance_custom_km': '7'})
        self.assertEqual(scope['distance'], 'custom')
        self.assertEqual(scope['distance_custom_km'], '7')
        scope = market_study.normalize_summary_scope(
            {'mode': 'distance', 'distance': 'bogus'})
        self.assertEqual(scope['distance'], '10')


class SummaryScopePromptTests(unittest.TestCase):

    def test_default_prompt_keeps_the_single_neighbour_rule(self):
        prompt = market_study.build_summary_user_prompt({}, [])
        self.assertIn('حيين مجاورين مختلفين ممنوع', prompt)
        self.assertIn('المفاتيح الإلزامية لمحاور summary', prompt)

    def test_city_scope_names_every_city_and_forbids_the_rest(self):
        prompt = market_study.build_summary_user_prompt(
            {'summaryScope': {'mode': 'city', 'places': ['جدة', 'مكة']}}, [])
        self.assertIn('جدة', prompt)
        self.assertIn('مكة', prompt)
        self.assertIn('غير مدخلة', prompt)
        self.assertNotIn('حيين مجاورين مختلفين ممنوع', prompt)

    def test_district_scope_names_every_district(self):
        prompt = market_study.build_summary_user_prompt(
            {'summary_scope': {'mode': 'district',
                               'places': ['النرجس', 'الياسمين']}}, [])
        self.assertIn('النرجس', prompt)
        self.assertIn('الياسمين', prompt)
        self.assertNotIn('البديل الأقرب الوحيد', prompt)

    def test_listed_scope_english_variant(self):
        prompt = market_study.build_summary_user_prompt(
            {'summaryScope': {'mode': 'city', 'places': ['Jeddah']}},
            [], offer_lang='en')
        self.assertIn('Jeddah', prompt)
        self.assertIn('unlisted', prompt)

    def test_research_prompt_carries_the_listed_scope(self):
        prompt = market_study.build_summary_chat_research_prompt(
            {'city': 'جدة',
             'summaryScope': {'mode': 'district', 'places': ['النرجس']}},
            'demand', 'ابحث عن الطلب', [], {}, [])
        self.assertIn('النرجس', prompt)
        self.assertIn('بحث جوجل الأصلي', prompt)

    def test_distance_scope_binds_to_own_distance_not_competitors(self):
        # Regression: the distance scope used to point at the competitors
        # radius, so a 3 km summary with a 10 km competitor radius still
        # analyzed 10 km. It must bind to its own distance instead.
        payload = {
            'summaryScope': {'mode': 'distance', 'distance': '3'},
            'resolvedRadiusKm': 10,
            'competitorRadiusLabel': '10 km',
        }
        block = market_study._summary_scope_block(payload)
        self.assertIn('نطاق 3 كم', block)
        self.assertIn('نطاق الملخص', block)
        self.assertIn('جدول المنافسين فقط', block)
        self.assertNotIn('نطاق المنافسين المحدد فيها', block)
        self.assertIn('حيين مجاورين مختلفين ممنوع', block)

    def test_distance_scope_english_binds_to_own_distance(self):
        payload = {
            'summaryScope': {'mode': 'distance', 'distance': '5'},
            'resolvedRadiusKm': 10,
            'competitorRadiusLabel': '10 km',
        }
        block = market_study._summary_scope_block(payload, 'en')
        self.assertIn('summary scope', block.lower())
        self.assertIn('competitors table only', block)
        self.assertNotIn('competitor scope stated there', block)

    def test_project_block_shows_both_scopes_separately(self):
        # The project facts must carry the two frames side by side so the
        # model never reads the competitors line as the summary frame.
        payload = {
            'summaryScope': {'mode': 'distance', 'distance': '3'},
            'resolvedRadiusKm': 10,
            'competitorRadiusLabel': '10 km',
        }
        block = market_study._project_input_block(payload)
        self.assertIn('نطاق المنافسين (لجدول المنافسين فقط)', block)
        self.assertIn('نطاق الملخص (الملزم لمحاور الملخص)', block)
        self.assertIn('نطاق 3 كم', block)

    def test_city_scope_binds_market_definition_to_listed_cities(self):
        # Regression: with scope جدة+الرياض the model wrote market_definition
        # as "حي الأندلس ضمن نطاق المنافسين 3 كم" instead of the two cities.
        payload = {
            'city': 'جدة',
            'district': 'الأندلس',
            'summaryScope': {'mode': 'city', 'places': ['جدة', 'الرياض']},
            'resolvedRadiusKm': 3,
            'competitorRadiusLabel': '3 km',
        }
        block = market_study._summary_scope_block(payload)
        self.assertIn('جدة', block)
        self.assertIn('الرياض', block)
        self.assertIn('تعريف السوق', block)
        self.assertIn('ولا تذكر نطاق المنافسين', block)
        prompt = market_study.build_summary_user_prompt(payload, [])
        self.assertIn('جدة', prompt)
        self.assertIn('الرياض', prompt)

    def test_city_scope_english_binds_market_definition(self):
        block = market_study._summary_scope_block(
            {'summaryScope': {'mode': 'city', 'places': ['Jeddah', 'Riyadh']}},
            'en')
        self.assertIn('Jeddah', block)
        self.assertIn('Riyadh', block)
        self.assertIn('market_definition', block)

    def test_distance_scope_binds_market_definition_to_summary_distance(self):
        payload = {
            'summaryScope': {'mode': 'distance', 'distance': '3'},
            'resolvedRadiusKm': 10,
            'competitorRadiusLabel': '10 km',
        }
        block = market_study._summary_scope_block(payload)
        self.assertIn('تعريف السوق', block)
        self.assertIn('ولا تذكر نطاق المنافسين كنطاق السوق', block)


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

    def test_payload_normalizes_the_summary_scope(self):
        module = self.application_module
        payload = module._prepare_market_payload(
            {'projectData': {'city': 'جدة'},
             'summaryScope': {'mode': 'city', 'places': ['جدة', 'مكة']}},
            tenant_id=None)
        self.assertEqual(payload['summaryScope']['mode'], 'city')
        self.assertEqual(payload['summaryScope']['places'], ['جدة', 'مكة'])

    def test_payload_without_scope_stays_historical(self):
        module = self.application_module
        payload = module._prepare_market_payload(
            {'projectData': {'city': 'جدة'}}, tenant_id=None)
        self.assertEqual(payload['summaryScope']['mode'], 'distance')


class SummaryScopeFrontendTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-scope-fe.db')
        import app as application_module
        cls.application_module = application_module
        cls.frontend = read_frontend_text(application_module.FRONTEND_JS_ORDER)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_scope_controls_exist_and_persist(self):
        text = self.frontend
        self.assertIn('marketSummaryScopeMode', text)
        self.assertIn('marketSummaryScopeDistance', text)
        self.assertIn('marketSummaryScopePlaces', text)
        self.assertIn('summary_scope', text)
        self.assertIn('addMarketSummaryScopePlace', text)

    def test_scope_controls_live_above_the_summary(self):
        # Owner rule: the scope picker belongs to the executive-summary
        # block, not to the competitors scope block at the top.
        text = self.frontend
        scope_at = text.index('marketSummaryScopeMode')
        summary_at = text.index('الملخص التنفيذي لسوق المشروع')
        generate_at = text.index('marketGenerateSummaryBtn')
        competitors_at = text.index('marketCompetitorRadius')
        self.assertGreater(scope_at, summary_at)
        self.assertLess(scope_at, generate_at)
        self.assertGreater(scope_at, competitors_at)

    def test_summary_generation_refuses_an_empty_listed_scope(self):
        # A city/district mode with no names cannot bind any figure — the
        # run is refused in the browser before any request is sent.
        text = self.frontend
        self.assertIn('market.summary_scope_required', text)
        self.assertIn('collectMarketSummaryScope', text)


if __name__ == '__main__':
    unittest.main()
