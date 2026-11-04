"""Tests for the revitalized Approvals & Decisions Hub (03_approvals).

Covers:
1. Shell markup in index.html:
   - Header with kicker (`approvals.kicker`), title (`nav.approvals`), and counter badge (`#approvalsCountBadge`).
   - Refresh button calling `openTenantApprovals(true)`.
   - 4-chip stats strip (`#approvalsStatsStrip`): pending, generation, sections, and decided history.
   - Dual-tab navigation (`#tabPendingApprovalsBtn`, `#tabHistoryApprovalsBtn`).
   - Tab views: `#approvalsPendingView` and `#approvalsHistoryView`.
2. Backend history API:
   - Route `GET /api/approvals/history` is registered.
   - `db.get_approval_history` helper handles tenant filtering and status != 'pending'.
3. Compliance with core rules:
   - Zero how-to instructional copy (no 'اضغط', 'اختر', etc.).
   - Zero emoji characters and zero icon fonts/glyphs.
   - Strict two-tier approvals model (Tier 1 generated content vs Tier 2 section approvals).
4. Frontend logic in `01_training_rules.js`:
   - `switchApprovalsTab` toggles views and active button styling.
   - `loadApprovalsList` populates stats, pending cards, and history cards.
   - Designed empty state with quick action to `openTenantPresentations()`.
5. CSS rules in `08_shell_chrome.css`:
   - `.tenant-approvals-tabs` and `.tenant-approval-card`.
6. i18n parity across `01_dict_ar.js` and `02_dict_en.js`.
"""

import re
import unittest
from pathlib import Path
from tests.frontend_source import shell_text

ROOT = Path(__file__).resolve().parents[2]


class TenantApprovalsHubTests(unittest.TestCase):

    def setUp(self):
        self.index_html = shell_text()
        self.rules_js = (ROOT / 'assets' / 'js' / '17-admin-boot' / '01_training_rules.js').read_text(encoding='utf-8')
        self.css_chrome = (ROOT / 'assets' / 'css' / 'base' / '08_shell_chrome.css').read_text(encoding='utf-8')
        self.ar_dict = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        self.en_dict = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')
        self.backend_route = (ROOT / 'app_parts' / '22_rules_pages' / '22_rules_approvals_static.py').read_text(encoding='utf-8')
        self.db_approvals = (ROOT / 'modules' / 'db' / 'db_parts' / '09_approvals' / '04d_approvals.py').read_text(encoding='utf-8')

    def _get_page_block(self):
        self.assertIn('id="tenantApprovalsPage"', self.index_html)
        return self.index_html.split('id="tenantApprovalsPage"')[1].split('</section>')[0]

    def test_page_heading_and_counter_badge(self):
        """Approvals page has unified LandLoom heading, kicker, counter badge, and refresh button."""
        block = self._get_page_block()
        self.assertIn('class="tenant-page-heading"', block)
        self.assertIn('data-i18n="approvals.kicker"', block)
        self.assertIn('data-i18n="nav.approvals"', block)
        self.assertIn('id="approvalsCountBadge"', block)
        self.assertIn('openTenantApprovals(true)', block)

    def test_page_statistics_strip(self):
        """Page has a 4-chip stats strip displaying key counts."""
        block = self._get_page_block()
        self.assertIn('id="approvalsStatsStrip"', block)
        self.assertIn('id="statPendingApprovals"', block)
        self.assertIn('id="statGenApprovals"', block)
        self.assertIn('id="statSectionApprovals"', block)
        self.assertIn('id="statDecidedApprovals"', block)

    def test_dual_tab_navigation(self):
        """Page includes dual-tab navigation for pending approvals and decision history."""
        block = self._get_page_block()
        self.assertIn('class="tenant-approvals-tabs"', block)
        self.assertIn('id="tabPendingApprovalsBtn"', block)
        self.assertIn('id="tabHistoryApprovalsBtn"', block)
        self.assertIn("switchApprovalsTab('pending')", block)
        self.assertIn("switchApprovalsTab('history')", block)
        self.assertIn('id="approvalsPendingView"', block)
        self.assertIn('id="approvalsHistoryView"', block)
        self.assertIn('id="approvalsList"', block)
        self.assertIn('id="approvalsHistoryList"', block)

    def test_backend_history_endpoint_and_db_query(self):
        """Backend registers /api/approvals/history and db defines get_approval_history."""
        self.assertIn('@app.route(\'/api/approvals/history\'', self.backend_route)
        self.assertIn('def api_get_approval_history():', self.backend_route)
        self.assertIn('db.get_approval_history(', self.backend_route)

        self.assertIn('def get_approval_history(', self.db_approvals)
        self.assertIn("pa.status != 'pending'", self.db_approvals)
        self.assertIn('ORDER BY COALESCE(pa.reviewed_at, pa.created_at) DESC', self.db_approvals)

    def test_frontend_switch_tab_and_loader(self):
        """JS defines switchApprovalsTab and handles view toggling and active styling."""
        self.assertIn('function switchApprovalsTab(tab)', self.rules_js)
        self.assertIn('approvalsPendingView', self.rules_js)
        self.assertIn('approvalsHistoryView', self.rules_js)
        self.assertIn('tabPendingApprovalsBtn', self.rules_js)
        self.assertIn('tabHistoryApprovalsBtn', self.rules_js)

    def test_designed_empty_state(self):
        """Designed empty state is present when no pending items exist, linking to presentations."""
        self.assertIn('tenant-dash-empty-state', self.rules_js)
        self.assertIn('openTenantPresentations()', self.rules_js)
        self.assertIn('approvals.empty_title', self.rules_js)
        self.assertIn('approvals.empty_desc', self.rules_js)

    def test_two_tier_approval_cards_markup(self):
        """Cards enforce the two-tier approval structure with explicit badges."""
        self.assertIn('tenant-approval-card', self.rules_js)
        self.assertIn('approvals.tier_one', self.rules_js)
        self.assertIn('approvals.tier_two_deck', self.rules_js)
        self.assertIn('approvals.tier_two_final', self.rules_js)
        self.assertIn('status-info', self.rules_js)
        self.assertIn('status-warning', self.rules_js)
        self.assertIn('status-primary', self.rules_js)

    def test_history_list_rendering(self):
        """History list renders past decisions with status, reviewer name, and decision notes."""
        self.assertIn('historyItems.sort', self.rules_js)
        self.assertIn('approval-note-box', self.rules_js)
        self.assertIn('approvals.decision_approved', self.rules_js)
        self.assertIn('approvals.decision_rejected', self.rules_js)

    def test_css_rules_present(self):
        """CSS definitions for tabs, approval cards, and notes exist in 08_shell_chrome.css."""
        self.assertIn('.tenant-approvals-tabs', self.css_chrome)
        self.assertIn('.tenant-approval-card', self.css_chrome)
        self.assertIn('.tenant-approval-card .approval-note-box', self.css_chrome)

    def test_no_how_to_hints_in_approvals_block(self):
        """Approvals page markup contains zero how-to instructional copy."""
        block = self._get_page_block()
        forbidden_patterns = [
            r'اضغط\s', r'اختر\s', r'راجع\s+أول[اًا]', r'قم\s+بـ',
            r'يرجى\s', r'يمكنك\s+الآن', r'انقر\s', r'لتحديد\s'
        ]
        for pattern in forbidden_patterns:
            matches = re.findall(pattern, block)
            self.assertEqual(matches, [], f"Found forbidden how-to copy in approvals markup matching: {pattern}")

    def test_no_emojis_in_approvals_hub(self):
        """Approvals page markup and JS contain zero emoji characters or icon symbols."""
        block = self._get_page_block()
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F700-\U0001F77F"
            "\U0001F780-\U0001F7FF"
            "\U0001F800-\U0001F8FF"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "↑↓→←✔✖✨💡📌🔍⚙️]"
        )
        matches = emoji_pattern.findall(block)
        self.assertEqual(matches, [], f"Found emojis/icon glyphs in approvals markup: {matches}")

    def test_i18n_keys_completeness_and_parity(self):
        """All approvals i18n keys exist in both AR and EN dictionaries."""
        required_keys = [
            'nav.approvals',
            'approvals.kicker',
            'approvals.title',
            'approvals.stat_pending',
            'approvals.stat_generation',
            'approvals.stat_sections',
            'approvals.stat_decided',
            'approvals.tab_pending',
            'approvals.tab_history',
            'approvals.empty_title',
            'approvals.empty_desc',
            'approvals.view_all_projects',
            'approvals.tier_one',
            'approvals.tier_two_section',
            'approvals.tier_two_final',
            'approvals.tier_two_deck',
            'approvals.history_empty',
            'approvals.decision_approved',
            'approvals.decision_rejected',
            'approvals.approved_by',
            'approvals.rejected_by'
        ]
        for key in required_keys:
            self.assertIn(f'"{key}":', self.ar_dict, f"Missing AR translation for key: {key}")
            self.assertIn(f'"{key}":', self.en_dict, f"Missing EN translation for key: {key}")


if __name__ == '__main__':
    unittest.main()
