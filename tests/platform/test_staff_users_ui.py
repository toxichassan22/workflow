import re
import sys
import unittest
from pathlib import Path
from tests.frontend_source import shell_text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application_module
import auth
import db


class StaffUsersUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application_module.app
        cls.client = cls.app.test_client()

    def _page_html(self):
        content = shell_text()
        start = content.find('id="tenantUsersPage"')
        self.assertNotEqual(start, -1, 'tenantUsersPage must exist in the shell')
        end = content.find('</section>', start)
        self.assertNotEqual(end, -1, 'tenantUsersPage section must be closed')
        return content[start:end]

    def _js(self, name):
        return (ROOT / 'assets' / 'js' / '17-admin-boot' / name).read_text(encoding='utf-8')

    def test_page_has_one_team_table_and_a_roles_guide(self):
        """The screen is one table plus a role guide beside it — not a tall
        always-open form whose trailing card appeared cut off below the fold."""
        html = self._page_html()
        for token in ('staff-container', 'staff-summary', 'staff-table',
                      'tenantUsersList', 'tenantInvitesList', 'staff-roles-card',
                      'users.role_guide_title'):
            self.assertIn(token, html)
        self.assertNotIn('class="staff-side"', html)
        self.assertNotIn('id="staffInviteCard"', html)

    def test_invite_form_is_a_dialog_opened_by_one_button(self):
        html = self._page_html()
        self.assertIn('id="staffInviteModal"', html)
        modal_tag = html.split('id="staffInviteModal"')[1][:240]
        self.assertIn('hidden', modal_tag)
        self.assertIn('openStaffInviteModal()', html)
        self.assertNotIn('focusStaffInviteForm', html)
        for field in ('newUserName', 'newUserEmail', 'newUserResponsibility',
                      'newUserPhone', 'newUserPassword', 'inviteProjectsPicker',
                      'staffRoleHint'):
            self.assertIn('id="%s"' % field, html)
        js = self._js('01_training_rules.js')
        self.assertIn('function openStaffInviteModal()', js)
        self.assertIn('function closeStaffInviteModal()', js)
        self.assertIn('modal.parentElement !== document.body', js)

    def test_permissions_panel_is_grouped_and_tabbed(self):
        js = self._js('02_users_roles.js')
        for token in ('STAFF_PERMISSION_GROUPS', 'data-staff-perm-tab',
                      'data-staff-perm-pane', 'staff-perm-tab', 'staff-toggle',
                      'staff-check-chip', 'function closeUserPermissionsModal()',
                      'function showStaffPermTab('):
            self.assertIn(token, js)
        for group in ('users.perm_group_access', 'users.perm_group_generation',
                      'users.perm_group_approvals', 'users.perm_group_settings'):
            self.assertIn(group, js)

    def test_permissions_save_sends_only_grantable_keys(self):
        """The save used to post every label-map key, sag_admin_panel included.
        The API rejects that platform-only key with 400, so each save surfaced an
        error although the grants had already landed. The payload is now driven
        by the server's availableKeys, which never carries it."""
        js = self._js('02_users_roles.js')
        self.assertIn('availableKeys: permData.availableKeys', js)
        save_block = js.split('async function saveUserPermissions()', 1)[1]
        save_block = save_block.split('// ── Presentation Versions', 1)[0]
        self.assertIn('editingUserPermissions.availableKeys', save_block)
        self.assertNotIn('Object.keys(PERMISSION_LABELS)', save_block)

    def test_the_separation_of_duties_screen_is_gone(self):
        """The staff page no longer offers a separation-of-duties screen: its
        button and both modals are gone. The two self-approval policies stay
        enforced server-side with their defaults."""
        html = self._page_html()
        self.assertNotIn('showSodMatrixModal', html)
        js = self._js('02_users_roles.js')
        self.assertNotIn('showSodMatrixModal', js)
        self.assertNotIn('saveSodPolicy', js)
        self.assertNotIn('/api/policies', js)
        policies_api = (ROOT / 'app_parts' / '20_admin' / '26_roles_policies.py').read_text(encoding='utf-8')
        self.assertIn("@app.route('/api/policies', methods=['PUT'])", policies_api)

    def test_no_emojis_or_icon_glyphs(self):
        html = self._page_html()
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe00-\ufe0f]'
        )
        self.assertEqual(emoji_pattern.findall(html), [])
        for arrow in ('↑', '↓', '→', '←', '▶', '◀', '▲', '▼'):
            self.assertNotIn(arrow, html)
        css = (ROOT / 'assets' / 'css' / 'base' / '15_staff_users.css').read_text(encoding='utf-8')
        self.assertEqual(emoji_pattern.findall(css), [])

    def test_no_static_how_to_copy(self):
        html = self._page_html()
        for phrase in ('اضغط', 'راجع أولاً', 'راجع اولا', 'اختر ثم', 'انقر هنا', 'يرجى'):
            self.assertNotIn(phrase, html)

    def test_css_is_registered_and_uses_brand_palette(self):
        css_path = ROOT / 'assets' / 'css' / 'base' / '15_staff_users.css'
        self.assertTrue(css_path.is_file(), '15_staff_users.css must exist')
        css = css_path.read_text(encoding='utf-8')
        for token in ('.staff-container', '.staff-table', '.staff-modal-overlay',
                      '.staff-toggle', '.staff-check-chip', '.staff-perm-tab'):
            self.assertIn(token, css)
        self.assertIn('#07182C', css)
        self.assertIn('#17C8E3', css)
        bundles = (ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py').read_text(encoding='utf-8')
        self.assertIn("'base/15_staff_users.css'", bundles)

    def test_new_strings_are_in_both_dictionaries(self):
        ar = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        en = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')
        keys = (
            'users.page_title', 'users.page_subtitle', 'users.invite_new',
            'users.team_title', 'users.role_guide_title', 'users.form_title',
            'users.add_button', 'users.permissions_title', 'users.permissions_subtitle',
            'users.perm_tab_app', 'users.perm_tab_sections', 'users.perm_tab_scope',
            'users.perm_group_access', 'users.perm_group_generation',
            'users.perm_group_approvals', 'users.perm_group_settings', 'users.perm_save',
        )
        for key in keys:
            self.assertIn('"%s"' % key, ar, 'missing Arabic key %s' % key)
            self.assertIn('"%s"' % key, en, 'missing English key %s' % key)
        html = self._page_html()
        for key in ('users.page_title', 'users.invite_new', 'users.role_guide_title',
                    'users.form_title', 'users.add_button'):
            self.assertIn('data-i18n="%s"' % key, html)

    def test_invites_report_carries_responsibility(self):
        """The invite row's role pill reads responsibility; the report query
        omitted the column, so every invite rendered as «موظف»."""
        with self.app.app_context():
            db.init_db()
            tenant = db.get_tenant_by_email('staff-report@example.test')
            if tenant:
                tenant_id = tenant['id']
            else:
                tenant_id = db.create_tenant(
                    'Staff Report Co', 'staff-report@example.test',
                    auth.hash_password('TestPass123!'), 'staff-report'
                )
            invite = db.create_invite(
                tenant_id, 'planner@staff-report.test', name='Planner', responsibility='editor'
            )
            report = db.tenant_users_report(tenant_id)
            rows = [i for i in report['invites'] if i['id'] == invite['id']]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get('responsibility'), 'editor')


if __name__ == '__main__':
    unittest.main()
