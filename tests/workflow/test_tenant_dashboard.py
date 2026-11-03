"""Tests for the revitalized Tenant Dashboard.

Covers:
1. Shell markup: `#dashboardRecentSection` and `#dashRecentProjects` presence,
   data-i18n attributes, no how-to copy, no emojis or icons.
2. Number & points formatting in `02a_admin_charts.js`: avoids floating point
   artifacts (e.g. 870.2657... -> 870.27, 1129.73... -> 1,129.73).
3. Month tick distribution in `02a_admin_charts.js`: 12-month interval
   spacing without erratic tick popping or skipping.
4. Recent projects rendering in `01_presentations.js`: empty states and populated rows.
5. Balance pill width in `04_export_responsive.css`: expanded max-width preventing badge truncation.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TenantDashboardRevitalizationTests(unittest.TestCase):

    def setUp(self):
        self.index_html = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.charts_js = (ROOT / 'assets' / 'js' / '16-presentations-export' / '02a_admin_charts.js').read_text(encoding='utf-8')
        self.pres_js = (ROOT / 'assets' / 'js' / '16-presentations-export' / '01_presentations.js').read_text(encoding='utf-8')
        self.routing_js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '01_routing.js').read_text(encoding='utf-8')
        self.css_responsive = (ROOT / 'assets' / 'css' / 'base' / '04_export_responsive.css').read_text(encoding='utf-8')
        self.css_chrome = (ROOT / 'assets' / 'css' / 'base' / '08_shell_chrome.css').read_text(encoding='utf-8')
        self.ar_dict = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        self.en_dict = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')

    def test_dashboard_markup_contains_recent_projects_section(self):
        """Dashboard page contains the new Recent Projects section container."""
        self.assertIn('id="dashboardRecentSection"', self.index_html)
        self.assertIn('id="dashRecentProjects"', self.index_html)
        self.assertIn('data-i18n="dashboard.recent_projects"', self.index_html)
        self.assertIn('data-i18n="dashboard.recent_projects_sub"', self.index_html)
        self.assertIn('data-i18n="dashboard.view_all_projects"', self.index_html)

    def test_dashboard_markup_carries_no_how_to_instructions(self):
        """Dashboard contains only state/overview copy, no instructional 'how-to' text."""
        dashboard_block = self.index_html.split('id="tenantDashboardPage"')[1].split('</section>')[0]
        forbidden_instructions = ['اضغط', 'اختر', 'قم ب', 'يرجى', 'راجع أولاً']
        for phrase in forbidden_instructions:
            self.assertNotIn(phrase, dashboard_block, f"Forbidden instruction '{phrase}' found in dashboard markup")

    def test_dashboard_markup_contains_no_emojis_or_icon_fonts(self):
        """Dashboard markup has zero emoji characters and no icon libraries."""
        dashboard_block = self.index_html.split('id="tenantDashboardPage"')[1].split('</section>')[0]
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)
        self.assertFalse(emoji_pattern.search(dashboard_block), "Emoji found in dashboard markup")
        self.assertNotIn('fa-', dashboard_block)
        self.assertNotIn('lucide', dashboard_block)

    def test_dashboard_renders_recent_projects_in_routing(self):
        """loadDashboard invokes renderDashboardRecentProjects with fetched presentations."""
        self.assertIn('renderDashboardRecentProjects', self.routing_js)
        self.assertIn('renderDashboardRecentProjects(presData && presData.presentations)', self.routing_js)

    def test_recent_projects_render_function_defined(self):
        """renderDashboardRecentProjects handles empty state and presentation rows."""
        self.assertIn('function renderDashboardRecentProjects(presentations)', self.pres_js)
        self.assertIn('tenant-dash-empty-state', self.pres_js)
        self.assertIn('tenant-recent-project-row', self.pres_js)
        self.assertIn('openExistingPresentation', self.pres_js)
        self.assertIn('openProjectDraftById', self.pres_js)

    def test_number_formatting_rounds_floating_points(self):
        """sagFmtMoneyParts rounds floats to 2 decimal places and handles integers."""
        self.assertIn('const rounded = Math.round(n * 100) / 100;', self.charts_js)
        self.assertIn('const val = hasDecimals ? rounded.toFixed(2) : rounded;', self.charts_js)
        # Should not pass raw unrounded n into formatExactSystemNumber
        self.assertNotIn('number: formatExactSystemNumber(n, true)', self.charts_js)

    def test_chart_tick_candidate_distribution(self):
        """Chart candidates are evenly distributed across n-1 intervals when step > 1."""
        self.assertIn('const numIntervals = Math.max(1, Math.min(maxTicks - 1, Math.round((n - 1) / tickStep)));', self.charts_js)
        self.assertIn('Math.round(k * (n - 1) / numIntervals)', self.charts_js)

    def test_balance_pill_max_width_prevents_badge_truncation(self):
        """Package badge pill allows at least 65% width to prevent '...' truncation."""
        match = re.search(r'\.tenant-balance-pill\s*\{[^}]*max-width:\s*(\d+)%', self.css_responsive)
        self.assertTrue(match, "Could not find max-width percentage on .tenant-balance-pill")
        pct = int(match.group(1))
        self.assertGreaterEqual(pct, 65, f"tenant-balance-pill max-width is {pct}%, expected >= 65%")

    def test_dashboard_css_classes_in_shell_chrome(self):
        """Shell chrome stylesheet contains the styling for recent projects and lifecycle strip."""
        self.assertIn('.tenant-recent-projects-panel', self.css_chrome)
        self.assertIn('.tenant-recent-project-row', self.css_chrome)
        self.assertIn('.tenant-dash-empty-state', self.css_chrome)
        self.assertIn('#dashboardLifecycle .tenant-dash-card', self.css_chrome)
        self.assertIn('#dashboardStats .tenant-balance-card', self.css_chrome)

    def test_dashboard_i18n_keys_exist_in_both_languages(self):
        """All new dashboard translation keys exist in both Arabic and English dictionaries."""
        keys = [
            'dashboard.recent_projects',
            'dashboard.recent_projects_sub',
            'dashboard.view_all_projects',
            'dashboard.empty_title',
            'dashboard.empty_hint',
            'dashboard.status_draft',
            'dashboard.status_pending',
            'dashboard.status_approved',
            'dashboard.status_completed',
            'dashboard.open_deck',
            'dashboard.edit_project',
            'dashboard.untitled_deck',
        ]
        for key in keys:
            self.assertIn(f'"{key}"', self.ar_dict, f"Missing {key} in Arabic dictionary")
            self.assertIn(f'"{key}"', self.en_dict, f"Missing {key} in English dictionary")


if __name__ == '__main__':
    unittest.main()
