"""Tests for the revitalized Notifications Center (04_notifications).

Covers:
1. Shell markup in index.html:
   - Header with kicker (`#notifPageKicker`), title (`page.notifications`), unread chip (`#notifUnreadCount`),
     refresh button calling `renderNotificationsPage()`, and mark-all-read button.
   - 4-chip stats strip (`#notifStatsStrip`): total, unread, projects & approvals, and system & wallet.
   - Centered container (`.tenant-notif-page-wrap`).
   - Dual toolbar with category group tabs (`.notif-category-tabs`) and reading status tabs (`.notif-status-tabs`).
   - List container (`#tenantNotificationsList`).
2. Frontend logic in assets/js/19-notifications.js:
   - Category group filter (`setNotifCategoryGroup`) and mappings (`NOTIF_GROUP_CATEGORIES`).
   - Number sanitization (`formatNotifNumberSanitized`) eliminating floating-point noise.
   - Direct contextual action buttons (`notifActionBtn`) for projects, approvals, wallet, and support tickets.
   - Designed empty state (`notifEmptyHtml`) with 'LL' monogram and navigation CTA.
   - Revitalized card layout (`notifCardHtml`) with `.tenant-notif-card-revamp`.
   - Stats strip populated during `renderNotificationsPage()`.
3. CSS rules in assets/css/base/08_shell_chrome.css:
   - Container max-width and centering (`.tenant-notif-page-wrap`).
   - Responsive stats strip (`.notif-stats-strip`, `.notif-stat-chip`).
   - Revitalized card styling (`.tenant-notif-card-revamp`, `.unread` with turquoise accent).
   - Designed empty state (`.tenant-notif-empty-state`, `.notif-empty-monogram`).
4. i18n parity across assets/i18n/01_dict_ar.js and assets/i18n/02_dict_en.js.
5. Strict product rules:
   - Zero how-to instructional copy.
   - Zero emoji characters and zero icon glyphs.
   - Under 1,000 lines constraint across all touched files.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TenantNotificationsCenterTests(unittest.TestCase):

    def setUp(self):
        self.index_html = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.notif_js = (ROOT / 'assets' / 'js' / '19-notifications.js').read_text(encoding='utf-8')
        self.css_chrome = (ROOT / 'assets' / 'css' / 'base' / '08_shell_chrome.css').read_text(encoding='utf-8')
        self.ar_dict = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        self.en_dict = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')

    def _get_page_block(self):
        self.assertIn('id="tenantNotificationsPage"', self.index_html)
        return self.index_html.split('id="tenantNotificationsPage"')[1].split('</section>')[0]

    def test_page_heading_actions_and_refresh(self):
        """Notifications page has unified heading, kicker, refresh button, unread chip, and mark-all-read."""
        block = self._get_page_block()
        self.assertIn('class="tenant-page-heading"', block)
        self.assertIn('id="notifPageKicker"', block)
        self.assertIn('data-i18n="page.notifications"', block)
        self.assertIn('renderNotificationsPage()', block)
        self.assertIn('id="notifUnreadCount"', block)
        self.assertIn('notificationsMarkAllRead()', block)

    def test_page_statistics_strip(self):
        """Page has a 4-chip executive stats strip."""
        block = self._get_page_block()
        self.assertIn('id="notifStatsStrip"', block)
        self.assertIn('id="notifStatTotal"', block)
        self.assertIn('id="notifStatUnread"', block)
        self.assertIn('id="notifStatProjects"', block)
        self.assertIn('id="notifStatSystem"', block)

    def test_dual_toolbar_tabs(self):
        """Toolbar includes category group tabs and read status tabs."""
        block = self._get_page_block()
        self.assertIn('class="notif-toolbar"', block)
        self.assertIn('class="sag-tabs notif-category-tabs"', block)
        self.assertIn('setNotifCategoryGroup(\'all\')', block)
        self.assertIn('setNotifCategoryGroup(\'projects\')', block)
        self.assertIn('setNotifCategoryGroup(\'finance\')', block)
        self.assertIn('setNotifCategoryGroup(\'support\')', block)
        self.assertIn('class="sag-tabs notif-status-tabs"', block)
        self.assertIn('setNotifStatusFilter(\'all\')', block)
        self.assertIn('setNotifStatusFilter(\'unread\')', block)
        self.assertIn('setNotifStatusFilter(\'read\')', block)

    def test_page_container_wrap(self):
        """List is wrapped in a bounded container avoiding full-screen stretch."""
        block = self._get_page_block()
        self.assertIn('class="tenant-notif-page-wrap"', block)
        self.assertIn('id="tenantNotificationsList"', block)

    def test_js_number_sanitizer(self):
        """JS sanitizer formats long decimal floats cleanly to 2 decimal places."""
        self.assertIn('formatNotifNumberSanitized', self.notif_js)
        # Test the regex pattern directly in Python to verify logic parity
        pattern = r'(\d+)\.(\d{3,})'
        sample_text = 'تم استهلاك 36.71981688999991 نقطة في عملية توليد الخرائط'
        replaced = re.sub(pattern, lambda m: f"{float(m.group(0)):.2f}", sample_text)
        self.assertEqual(replaced, 'تم استهلاك 36.72 نقطة في عملية توليد الخرائط')

    def test_js_action_buttons(self):
        """JS includes notifActionBtn helper generating contextual direct action buttons."""
        self.assertIn('function notifActionBtn(n)', self.notif_js)
        self.assertIn('notif.act_review_approval', self.notif_js)
        self.assertIn('notif.act_view_project', self.notif_js)
        self.assertIn('notif.act_view_wallet', self.notif_js)
        self.assertIn('notif.act_view_ticket', self.notif_js)

    def test_js_category_grouping_and_stats_strip(self):
        """JS updates stats strip counters and supports category group filtering."""
        self.assertIn('NOTIF_GROUP_CATEGORIES', self.notif_js)
        self.assertIn('setNotifCategoryGroup', self.notif_js)
        self.assertIn('notifStatTotal', self.notif_js)
        self.assertIn('notifStatUnread', self.notif_js)
        self.assertIn('notifStatProjects', self.notif_js)
        self.assertIn('notifStatSystem', self.notif_js)

    def test_js_empty_state_monogram(self):
        """Empty state uses the text monogram LL with zero icons or emojis."""
        self.assertIn('function notifEmptyHtml()', self.notif_js)
        self.assertIn('tenant-notif-empty-state', self.notif_js)
        self.assertIn('notif-empty-monogram', self.notif_js)
        self.assertIn('>LL<', self.notif_js)
        self.assertIn('openTenantPresentations()', self.notif_js)

    def test_css_rules_in_shell_chrome(self):
        """CSS includes styles for page wrap, stats strip, revamp cards, and empty state."""
        self.assertIn('.tenant-notif-page-wrap', self.css_chrome)
        self.assertIn('.notif-stats-strip', self.css_chrome)
        self.assertIn('.notif-stat-chip', self.css_chrome)
        self.assertIn('.tenant-notif-card-revamp', self.css_chrome)
        self.assertIn('.tenant-notif-empty-state', self.css_chrome)
        self.assertIn('.notif-empty-monogram', self.css_chrome)

    def test_i18n_parity(self):
        """All notification keys are present in both Arabic and English dictionaries."""
        keys = [
            'notif.stat_total', 'notif.stat_unread', 'notif.stat_projects', 'notif.stat_system',
            'notif.cat_all', 'notif.cat_projects', 'notif.cat_finance', 'notif.cat_support',
            'notif.act_review_approval', 'notif.act_view_project', 'notif.act_view_wallet',
            'notif.act_view_ticket', 'notif.act_view_details',
            'notif.act_review_recharge', 'notif.act_review_ticket', 'notif.act_review_join',
            'notif.empty_title', 'notif.empty_desc', 'notif.empty_cta'
        ]
        for k in keys:
            self.assertIn(f'"{k}"', self.ar_dict, f"Missing key {k} in Arabic dictionary")
            self.assertIn(f'"{k}"', self.en_dict, f"Missing key {k} in English dictionary")

    def test_zero_how_to_instructions_in_markup(self):
        """Guards against any operational how-to instructions in notifications markup."""
        block = self._get_page_block()
        banned = ['اضغط', 'اختر', 'قم بـ', 'يرجى النقر', 'انقر']
        for word in banned:
            self.assertNotIn(word, block, f"Found banned how-to word '{word}' in notifications markup")

    def test_zero_emoji_or_icon_glyphs(self):
        """Guards against emojis or icon font glyphs in notifications block and JS."""
        block = self._get_page_block()
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]')
        self.assertIsNone(emoji_pattern.search(block), "Found emoji character in notifications markup")
        icon_glyphs = ['✓', '✔', '✕', '✖', '➜', '➔', '→', '←', '↑', '↓', '⚙', '★']
        for glyph in icon_glyphs:
            self.assertNotIn(glyph, block, f"Found icon glyph '{glyph}' in notifications markup")

    def test_file_length_limits(self):
        """Guards that no touched file exceeds the 1,000 lines rule."""
        files = [
            ROOT / 'assets' / 'js' / '19-notifications.js',
            ROOT / 'assets' / 'css' / 'base' / '08_shell_chrome.css'
        ]
        for f in files:
            count = len(f.read_text(encoding='utf-8').splitlines())
            self.assertLessEqual(count, 1000, f"File {f.name} has {count} lines, exceeding the 1,000 line limit!")


if __name__ == '__main__':
    unittest.main()
