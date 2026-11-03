"""Tests for the revitalized Presentations & Projects List (02_presentations_list).

Covers:
1. Shell markup in index.html:
   - Header with kicker (`projects.kicker`), title (`nav.projects`), and counter badge (`presentationsCountBadge`).
   - Direct 'مشروع جديد' action button in the page header.
   - 4-metric statistics strip (`#projectStatsStrip`) for total, in_progress, approved, and drafts.
   - Filter panel with search, status, date bounds, filter action, and reset action.
2. Compliance with core rules:
   - Zero how-to instructional copy (no 'اضغط', 'اختر', etc.).
   - Zero emoji characters and zero icon fonts/libraries.
3. Cost formatting & floating-point noise elimination:
   - `formatUsageCost` rounds floats to 2 decimals, eliminating 16-digit noise.
4. Clean table actions (Quiet Density):
   - Single primary action button per row ('فتح المشروع' / 'استعادة').
   - Contextual dropdown menu ('المزيد') for secondary actions.
5. Filter reset and statistics update helpers in `01_presentations.js`.
6. CSS architecture in `08_shell_chrome.css`.
7. Internationalization completeness across AR and EN dictionaries.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TenantPresentationsListTests(unittest.TestCase):

    def setUp(self):
        self.index_html = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.pres_js = (ROOT / 'assets' / 'js' / '16-presentations-export' / '01_presentations.js').read_text(encoding='utf-8')
        self.admin_dash_js = (ROOT / 'assets' / 'js' / '16-presentations-export' / '02_admin_dashboard.js').read_text(encoding='utf-8')
        self.css_chrome = (ROOT / 'assets' / 'css' / 'base' / '08_shell_chrome.css').read_text(encoding='utf-8')
        self.ar_dict = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        self.en_dict = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')

    def _get_page_block(self):
        self.assertIn('id="tenantPresentationsPage"', self.index_html)
        return self.index_html.split('id="tenantPresentationsPage"')[1].split('</section>')[0]

    def test_page_heading_markup_and_new_project_button(self):
        """Presentations page has dedicated heading, kicker, counter badge, and new project action."""
        block = self._get_page_block()
        self.assertIn('class="tenant-page-heading"', block)
        self.assertIn('data-i18n="projects.kicker"', block)
        self.assertIn('data-i18n="nav.projects"', block)
        self.assertIn('id="presentationsCountBadge"', block)
        self.assertIn('startTenantProject()', block)
        self.assertIn('data-i18n="nav.new_proposal"', block)

    def test_page_statistics_strip(self):
        """Page includes a 4-chip stats strip displaying key counts."""
        block = self._get_page_block()
        self.assertIn('id="projectStatsStrip"', block)
        self.assertIn('id="presStatTotal"', block)
        self.assertIn('id="presStatInProgress"', block)
        self.assertIn('id="presStatApproved"', block)
        self.assertIn('id="presStatDrafts"', block)
        self.assertIn('data-i18n="projects.stat_total"', block)
        self.assertIn('data-i18n="projects.stat_in_progress"', block)
        self.assertIn('data-i18n="projects.stat_approved"', block)
        self.assertIn('data-i18n="projects.stat_drafts"', block)

    def test_filter_panel_inputs_and_actions(self):
        """Filter panel contains search, status select, date range, filter and reset buttons."""
        block = self._get_page_block()
        self.assertIn('id="projectArchiveSearch"', block)
        self.assertIn('id="projectArchiveStatus"', block)
        self.assertIn('id="projectArchiveFrom"', block)
        self.assertIn('id="projectArchiveTo"', block)
        self.assertIn('openTenantPresentations(true)', block)
        self.assertIn('clearProjectArchiveFilters()', block)
        self.assertIn('onkeydown="if(event.key===\'Enter\') openTenantPresentations(true)"', block)

    def test_markup_carries_no_how_to_instructions(self):
        """Page markup states what things are, never how to operate them."""
        block = self._get_page_block()
        forbidden_instructions = ['اضغط', 'اختر', 'قم ب', 'يرجى', 'راجع أولاً']
        for phrase in forbidden_instructions:
            self.assertNotIn(phrase, block, f"Forbidden how-to instruction '{phrase}' found in markup")

    def test_markup_contains_no_emojis_or_icon_fonts(self):
        """Page markup has zero emoji characters and no icon libraries."""
        block = self._get_page_block()
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)
        self.assertFalse(emoji_pattern.search(block), "Emoji character found in presentations page markup")
        self.assertNotIn('fa-', block)
        self.assertNotIn('lucide', block)
        self.assertNotIn('<svg', block)

    def test_format_usage_cost_eliminates_floating_point_noise(self):
        """formatUsageCost rounds values to 2 decimal places to prevent 16-digit artifacts."""
        self.assertIn('function formatUsageCost(sar)', self.admin_dash_js)
        self.assertIn('const rounded = Math.round(value * 100) / 100;', self.admin_dash_js)
        self.assertIn('hasDecimals ? rounded.toFixed(2) : rounded', self.admin_dash_js)

    def test_contextual_dropdown_replaces_action_bloat(self):
        """Rows use a single primary button plus a dropdown 'المزيد' menu instead of 5 cramped buttons."""
        self.assertIn('toggleTenantDropdown(this)', self.pres_js)
        self.assertIn('tenant-dropdown-menu', self.pres_js)
        self.assertIn('openProjectDraftById', self.pres_js)
        self.assertIn('copyProjectDraftById', self.pres_js)
        self.assertIn('showDraftEditLog', self.pres_js)
        self.assertIn('showDraftVersions', self.pres_js)
        self.assertIn('deleteProjectDraftById', self.pres_js)

    def test_filter_reset_and_stats_updater_defined(self):
        """clearProjectArchiveFilters and updateProjectArchiveStats are defined and integrated."""
        self.assertIn('function clearProjectArchiveFilters()', self.pres_js)
        self.assertIn('function updateProjectArchiveStats(items)', self.pres_js)
        self.assertIn('updateProjectArchiveStats(drafts);', self.pres_js)

    def test_table_footer_and_empty_state_defined(self):
        """Table output includes footer summary count and styled empty state."""
        self.assertIn('tenant-table-footer', self.pres_js)
        self.assertIn('tenant-dash-empty-state', self.pres_js)
        self.assertIn('tenant-projects-table-panel', self.pres_js)

    def test_css_classes_in_shell_chrome(self):
        """Relevant CSS classes exist in 08_shell_chrome.css for layout and density."""
        classes = [
            '.tenant-projects-stats-strip',
            '.tenant-project-stat-chip',
            '.tenant-projects-filter-panel',
            '.tenant-projects-filter-grid',
            '.tenant-projects-table-panel',
            '.tenant-projects-table',
            '.tenant-table-footer',
        ]
        for cls in classes:
            self.assertIn(cls, self.css_chrome, f"CSS class '{cls}' not found in 08_shell_chrome.css")

    def test_i18n_keys_present_in_both_dictionaries(self):
        """All newly introduced projects.* keys exist in both AR and EN dictionaries."""
        keys = [
            'projects.kicker',
            'projects.search_label',
            'projects.search_placeholder',
            'projects.status_label',
            'projects.all_statuses',
            'projects.from_date',
            'projects.to_date',
            'projects.filter',
            'projects.reset',
            'projects.stat_total',
            'projects.stat_in_progress',
            'projects.stat_approved',
            'projects.stat_drafts',
            'projects.empty_title',
            'projects.empty_hint',
            'projects.unit',
            'projects.showing',
            'projects.name',
            'projects.status',
            'projects.total_cost',
            'projects.maps_cost',
            'projects.created_at',
            'projects.updated_at',
            'projects.actions',
            'projects.open',
            'projects.restore',
            'projects.copy',
            'projects.edit_log',
            'projects.delete',
            'projects.more',
        ]
        for key in keys:
            self.assertIn(f'"{key}"', self.ar_dict, f"Key '{key}' missing from 01_dict_ar.js")
            self.assertIn(f'"{key}"', self.en_dict, f"Key '{key}' missing from 02_dict_en.js")


if __name__ == '__main__':
    unittest.main()
