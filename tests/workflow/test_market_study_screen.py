"""Regression guards for the unified market study screen.

The section is one data surface: the same fields read and edit, approval locks
them in place, and the market tab stays navigable while approved. The source
register keeps its add/edit/delete behaviour and gains serial numbers.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_frontend_text():
    parts = [ROOT / 'index.html']
    for pattern in ('assets/css/**/*.css', 'assets/js/**/*.js'):
        parts.extend(sorted(ROOT.glob(pattern), key=lambda path: path.as_posix()))
    return '\n'.join(path.read_text(encoding='utf-8') for path in parts)


class MarketStudyScreenTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = read_frontend_text()

    def test_market_tabs_remain_navigable_when_the_section_is_approved(self):
        for tab_id in ('marketCompetitorsTab', 'marketMarketTab'):
            match = re.search(r'<button[^>]*id="' + tab_id + r'"[^>]*>', self.text)
            self.assertIsNotNone(match, tab_id)
            self.assertIn('data-section-lock-ignore="1"', match.group(0))

    def test_market_tab_is_the_default_analysis_view(self):
        match = re.search(r'<button[^>]*id="marketMarketTab"[^>]*>', self.text)
        self.assertIsNotNone(match)
        self.assertIn('market-study-tab active', match.group(0))
        self.assertIn('aria-selected="true"', match.group(0))

    def test_search_depth_control_is_removed(self):
        self.assertNotIn('marketSummaryResearchDepth', self.text)
        self.assertNotIn('عمق البحث', self.text)
        self.assertIn("state.summary_research_depth = 'full';", self.text)

    def test_unified_screen_orders_axes_swot_summary_and_sources(self):
        for token in (
            'id="marketStudySummaryBlock"',
            'id="marketStudyAxesBlock"',
            'id="marketStudySwotBlock"',
            'id="marketStudySourcesBlock"',
            'id="marketStudyToc"',
            'market-study-toc-toggle',
        ):
            self.assertIn(token, self.text)
        self.assertLess(self.text.index('id="marketStudyAxesBlock"'),
                        self.text.index('id="marketStudySwotBlock"'))
        self.assertLess(self.text.index('id="marketStudySwotBlock"'),
                        self.text.index('id="marketStudySummaryBlock"'))
        self.assertLess(self.text.index('id="marketStudySummaryBlock"'),
                        self.text.index('id="marketStudySourcesBlock"'))

    def test_summary_axes_use_editable_cards_and_normalized_display_values(self):
        self.assertIn('class="market-axis-card"', self.text)
        self.assertIn('class="market-auto-grow"', self.text)
        self.assertIn('function autoGrowMarketStudyFields()', self.text)
        self.assertIn('formatMarketSummaryFieldValue', self.text)
        self.assertIn('marketSwotDisplayValue', self.text)
        self.assertIn('field.value = formatMarketSummaryFieldValue', self.text)
        self.assertIn('field.value = marketSwotDisplayValue', self.text)

    def test_approval_locks_the_same_market_fields(self):
        self.assertIn("applySectionLockState('section-market-study'", self.text)
        self.assertIn("button.dataset.sectionLockIgnore = '1';", self.text)

    def test_one_block_summary_is_editable_and_collected(self):
        match = re.search(r'<textarea[^>]*id="marketStudyOneBlockSummary"[^>]*>', self.text)
        self.assertIsNotNone(match)
        self.assertNotIn('readonly', match.group(0).lower())
        self.assertIn(
            "const oneBlockField = document.getElementById('marketStudyOneBlockSummary');",
            self.text)

    def test_executive_summary_uses_the_full_content_width(self):
        rule = re.search(
            r'#section-market-study \.market-study-one-block \{[^}]*\}', self.text)
        self.assertIsNotNone(rule)
        self.assertIn('max-width: none', rule.group(0))

    def test_sources_table_keeps_edit_add_delete_and_serial_numbers(self):
        self.assertIn('data-i18n="market.sources_serial"', self.text)
        self.assertIn('الرقم', self.text)
        self.assertIn('data-source-serial', self.text)
        self.assertIn('function renumberMarketSourceRows()', self.text)
        self.assertIn('marketSourcesCount', self.text)
        self.assertIn('data-field="name"', self.text)
        self.assertIn('data-field="url"', self.text)
        self.assertIn('data-field="data_date"', self.text)
        self.assertIn('data-remove-source', self.text)
        self.assertIn('function addMarketSourceRow', self.text)


if __name__ == '__main__':
    unittest.main()
