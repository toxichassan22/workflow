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
