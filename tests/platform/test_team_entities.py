"""The company team library: reorder rules and the approved screen contract.

The library is one flat list shared by every project file. Reordering it is a
write to the library itself, so the route must accept exactly the set of ids the
tenant owns and refuse anything else. The screen assertions pin the decisions
the owner approved: equal-height cards, a two-line brief with a fade, one
add/edit drawer with a single cancel action, and the turquoise primary CTA.
"""

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.frontend_source import shell_text  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402


class TeamEntityReorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'team-entities.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            # Importing app is a no-op when another suite already imported it.
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        with self.app.app_context():
            self.tenant = db.create_tenant(
                'Team Co ' + suffix, f'team-{suffix}@example.test', 'hash', 'team-' + suffix)
        self.token = auth.create_token(
            self.tenant, f'team-{suffix}@example.test', user_id=None,
            user_name='Team Admin', user_role='company_admin')
        self.client = self.app.test_client()

    def _headers(self):
        return {'Authorization': 'Bearer ' + self.token}

    def _create(self, name, sort_order):
        with self.app.app_context():
            return db.create_team_entity(self.tenant, name, sort_order=sort_order)

    def _names(self):
        response = self.client.get('/api/team-entities', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        return [item['name'] for item in response.get_json()['entities']]

    def _reorder(self, entity_ids):
        return self.client.post(
            '/api/team-entities/reorder', headers=self._headers(),
            json={'entityIds': entity_ids})

    def test_reorder_persists_the_visible_order(self):
        first = self._create('الجهة الأولى', 10)
        second = self._create('الجهة الثانية', 20)
        third = self._create('الجهة الثالثة', 30)
        self.assertEqual(self._names(), ['الجهة الأولى', 'الجهة الثانية', 'الجهة الثالثة'])

        response = self._reorder([third, first, second])
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual([item['name'] for item in payload['entities']],
                         ['الجهة الثالثة', 'الجهة الأولى', 'الجهة الثانية'])
        self.assertEqual([item['sortOrder'] for item in payload['entities']], [10, 20, 30])
        self.assertEqual(self._names(), ['الجهة الثالثة', 'الجهة الأولى', 'الجهة الثانية'])

    def test_reorder_refuses_a_partial_duplicate_or_foreign_list(self):
        first = self._create('جهة أ', 10)
        second = self._create('جهة ب', 20)
        third = self._create('جهة ج', 30)
        before = self._names()

        for bad_list in ([], [first, second], [first, first, second],
                         [first, second, 'foreign-entity-id']):
            response = self._reorder(bad_list)
            self.assertEqual(response.status_code, 400, bad_list)
            self.assertEqual(self._names(), before, bad_list)

    def test_reorder_never_crosses_tenants(self):
        first = self._create('جهة محلية', 10)
        suffix = uuid.uuid4().hex[:8]
        with self.app.app_context():
            other_tenant = db.create_tenant(
                'Other Co ' + suffix, f'other-{suffix}@example.test', 'hash', 'other-' + suffix)
            foreign_id = db.create_team_entity(other_tenant, 'جهة خارجية', sort_order=10)

        response = self._reorder([first, foreign_id])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._names(), ['جهة محلية'])
        with self.app.app_context():
            foreign = db.get_team_entity(other_tenant, foreign_id)
        self.assertEqual(foreign['sortOrder'], 10)

    def test_reorder_requires_company_settings(self):
        first = self._create('جهة أ', 10)
        second = self._create('جهة ب', 20)
        suffix = uuid.uuid4().hex[:8]
        with self.app.app_context():
            employee_id = db.create_user(
                self.tenant, 'موظف', f'employee-{suffix}@example.test', 'hash')
        employee_token = auth.create_token(
            self.tenant, f'employee-{suffix}@example.test', user_id=employee_id,
            user_name='موظف', user_role='employee')

        refused = self.client.post(
            '/api/team-entities/reorder',
            headers={'Authorization': 'Bearer ' + employee_token},
            json={'entityIds': [second, first]})
        self.assertEqual(refused.status_code, 403)

        with self.app.app_context():
            db.set_user_permission(employee_id, 'company_settings', True)
        allowed = self.client.post(
            '/api/team-entities/reorder',
            headers={'Authorization': 'Bearer ' + employee_token},
            json={'entityIds': [second, first]})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())


class TeamScreenContractTests(unittest.TestCase):
    """The decisions approved in the preview, pinned in the shipped source."""

    @classmethod
    def setUpClass(cls):
        cls.shell = shell_text()
        cls.start = cls.shell.index('id="tenantTeamPage"')
        cls.end = cls.shell.index('</section>', cls.start)
        cls.team_markup = cls.shell[cls.start:cls.end]
        cls.css = (ROOT / 'assets' / 'css' / 'base' / '16_dev_team.css').read_text(encoding='utf-8')
        cls.js = (ROOT / 'assets' / 'js' / '06a-team-library.js').read_text(encoding='utf-8')

    def test_the_screen_has_one_header_and_one_add_action(self):
        self.assertIn('team-lib-cta', self.team_markup)
        self.assertIn('id="tenantTeamAddBtn"', self.team_markup)
        self.assertIn('id="tenantTeamCount"', self.team_markup)
        self.assertIn('data-i18n="team.title"', self.team_markup)
        self.assertNotIn('إضافة مطور', self.team_markup)
        self.assertNotIn('tenantTeamStats', self.team_markup)

    def test_the_drawer_has_one_cancel_action(self):
        self.assertIn('id="teamEntityDrawer"', self.team_markup)
        self.assertIn('id="teamEntitySaveBtn"', self.team_markup)
        self.assertIn('id="teamEntityCancelBtn"', self.team_markup)
        self.assertNotIn('teamPreviewClose', self.team_markup)
        self.assertNotIn('إغلاق', self.team_markup)

    def test_the_brief_is_two_lines_with_a_fade(self):
        self.assertIn('-webkit-line-clamp: 2', self.css)
        self.assertIn('.team-brief::after', self.css)
        self.assertIn('height: calc(2 * 1.75em)', self.css)
        self.assertIn('grid-auto-rows: 1fr', self.css)
        self.assertIn('min-height: 22px', self.css)

    def test_the_primary_action_carries_the_turquoise_brand_accent(self):
        cta_rule = self.css[self.css.index('.team-lib-cta {'):self.css.index('.team-lib-cta:hover')]
        self.assertIn('--teal-bright, #17C8E3', cta_rule)
        self.assertIn('var(--teal-soft, #DFF6FB)', self.css)

    def test_reordering_is_wired_to_the_library_route(self):
        self.assertIn('/api/team-entities/reorder', self.js)
        self.assertIn('handleTeamOrderKey', self.js)
        self.assertIn('teamLogoObjectUrl', self.js)
        self.assertIn("WFT('team.empty_title'", self.js)
        self.assertIn("WFT('team.logo_empty'", self.js)


if __name__ == '__main__':
    unittest.main()
