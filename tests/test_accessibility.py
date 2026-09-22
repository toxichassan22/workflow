"""Accessibility contract (t63).

Structural checks on the shell and the frontend bundle: every dialog is a
real labelled dialog, every overlay marked ``data-a11y-modal`` gets the shared
Escape/focus-trap behaviour from ``00-core.js``, clickable cards activate from
the keyboard, and form labels are programmatically bound to their controls.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INDEX = ROOT / 'index.html'

FRONTEND_CSS_ORDER = (
    'base/01_preview_chat.css', 'base/02_tenant_pages.css',
    'base/03_the_view_model.css', 'base/04_export_responsive.css',
    'base/05_dashboard_viz.css',
    'project-form/01_sections_changelog.css',
    'project-form/02_fields_tables_rail.css',
)
FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '06-team.js', '07-project-form.js', '08-location-maps.js', '09-financial.js',
    '10-financial-report-timeline.js', '11-land-croquis.js', '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js', '14-slides-gen.js', '15-slide-edit-chat.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js', '17-admin-boot.js', '18-landloom-ops.js',
    '19-notifications.js',
)


def read_shell():
    return INDEX.read_text(encoding='utf-8')


def read_frontend_text():
    """Shell + styles + scripts in load order: the whole client source."""
    parts = [read_shell()]
    for name in FRONTEND_CSS_ORDER:
        parts.append((ROOT / 'assets' / 'css' / name).read_text(encoding='utf-8'))
    for name in FRONTEND_JS_ORDER:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


TAG_RE = re.compile(r'<[^>]+>')
ID_RE = re.compile(r'id="([^"]+)"')


def _modal_chunks(shell):
    """(id, markup) for each overlay-level div that wraps a dialog."""
    chunks = []
    for match in re.finditer(
            r'<div id="(ll\w+Modal|sagTenantModal|sagCompanyCreateModal|presentationFontSettingsPanel)"[^>]*>',
            shell):
        chunks.append((match.group(1), match.group(0)))
    return chunks


class DialogSemanticsTests(unittest.TestCase):
    def test_shell_is_rtl_arabic(self):
        self.assertIn('dir="rtl"', read_shell()[:500])
        self.assertIn('lang="ar"', read_shell()[:500])

    def test_every_dialog_role_is_modal_and_labelled(self):
        shell = read_shell()
        for tag in re.finditer(r'<[^>]+role="dialog"[^>]*>', shell):
            markup = tag.group(0)
            self.assertIn('aria-modal="true"', markup, markup)
            self.assertTrue(
                'aria-labelledby' in markup or 'aria-label' in markup, markup)

    def test_every_modal_overlay_carries_the_shared_marker(self):
        for modal_id, opening_tag in _modal_chunks(read_shell()):
            self.assertIn(
                'data-a11y-modal', opening_tag,
                f'{modal_id} misses data-a11y-modal so Escape/trap skip it')

    def test_loader_and_live_regions(self):
        shell = read_shell()
        self.assertIn('aria-live', shell)
        self.assertIn('role="progressbar"', shell)


class ImageAndLabelTests(unittest.TestCase):
    def test_every_shell_image_has_alt(self):
        for tag in re.finditer(r'<img\b[^>]*>', read_shell()):
            self.assertIn('alt=', tag.group(0), tag.group(0))

    def test_modal_labels_are_bound_to_controls(self):
        shell = read_shell()
        ids = set(ID_RE.findall(shell))
        for modal_id, opening_tag in _modal_chunks(shell):
            start = shell.find(opening_tag)
            end = shell.find('<!--', start + len(opening_tag))
            if end == -1:
                end = len(shell)
            chunk = shell[start:end]
            for label in re.finditer(r'<label\b[^>]*>', chunk):
                markup = label.group(0)
                if 'for="' in markup:
                    target = re.search(r'for="([^"]+)"', markup).group(1)
                    self.assertIn(target, ids,
                                  f'{modal_id}: label points at missing id {target}')
                else:
                    # a label wrapping its control is associated without for=
                    after = chunk[label.end():label.end() + 300]
                    self.assertRegex(
                        after.split('</label>')[0],
                        r'<(input|select|textarea)\b',
                        f'{modal_id}: unbound label {markup}')

    def test_no_positive_tabindex_anywhere(self):
        self.assertIsNone(
            re.search(r'tabindex="[1-9]', read_frontend_text()),
            'positive tabindex breaks the natural focus order')


class KeyboardActivationTests(unittest.TestCase):
    def test_shared_modal_helpers_exist(self):
        src = read_frontend_text()
        for name in ('a11yVisibleModal', 'a11yModalDidOpen', 'a11yModalDidClose',
                     'data-a11y-modal', "event.key === 'Escape'",
                     "event.key === 'Tab'"):
            self.assertIn(name, src, name)

    def test_modal_openers_drive_focus_into_the_dialog(self):
        src = read_frontend_text()
        # openLlModal, openSagCompanyCreate, openPresentationFontSettings and
        # the tenant-details modal all funnel through a11yModalDidOpen.
        self.assertGreaterEqual(src.count('a11yModalDidOpen('), 4)

    def test_clickable_cards_activate_from_keyboard(self):
        src = read_frontend_text()
        bad = []
        for tag in re.finditer(r'<[^>]*cursor:pointer[^>]*onclick=|<[^>]*onclick=[^>]*cursor:pointer[^>]*>', src):
            markup = tag.group(0)
            # native <button>/<a> already activate on Enter/Space
            if re.match(r'<(button|a)\b', markup):
                continue
            if 'role="button"' not in markup or 'tabindex' not in markup:
                bad.append(markup[:140])
        self.assertEqual(bad, [], f'clickable cards without keyboard access: {bad}')

    def test_delegated_activation_handler_exists(self):
        src = read_frontend_text()
        self.assertIn("closest('[role=\"button\"]')", src)
        # a nested real control keeps its own action
        self.assertIn("closest('button, a[href], input, select, textarea", src)


if __name__ == '__main__':
    unittest.main()
