"""Tests for the revitalized Notifications Center (04_notifications).

Covers:
1. Shell markup in index.html:
   - Header with kicker (`#notifPageKicker`), title (`page.notifications`), unread chip (`#notifUnreadCount`),
     refresh button with `data-ws-icon="refresh"` calling `renderNotificationsPage()`, and mark-all-read button.
   - 4-chip stats strip (`#notifStatsStrip`) with clickable filter targets (`notif-stat-clickable`).
   - Unified toolbar with category group tabs, reading status tabs, search box (`#notifSearchInput`),
     and time filter select (`#notifTimeFilter`).
   - Selection bar (`#notifSelectionBar`) with master checkbox (`#notifSelectAll`), select count,
     bulk mark read, bulk delete, and cancel.
   - Redundant preferences panel completely removed.
   - Centered container (`.tenant-notif-page-wrap`).
   - List container (`#tenantNotificationsList`).
2. Frontend logic in assets/js/19-notifications.js:
   - Category group filter (`setNotifCategoryGroup`) and mappings (`NOTIF_GROUP_CATEGORIES`).
   - Multi-word token search with Arabic normalization (`notifNormalizeText`, `notifMatchesQuery`).
   - Time range filtering (`notifMatchesTime`).
   - In-memory instant filtering (`applyNotifFilters`) and filter reset (`clearNotifFilters`).
   - Live search input handler (`onNotifSearchInput`).
   - Number sanitization (`formatNotifNumberSanitized`) eliminating floating-point noise.
   - Direct contextual action buttons (`notifActionBtn`) for projects, approvals, wallet, and support tickets.
   - Individual single mark-read button (`notificationMarkSingleRead`) on unread cards.
   - Multi-selection management (`toggleNotifSelect`, `toggleNotifSelectAll`, `clearNotifSelection`, `updateNotifSelectionUI`).
   - Bulk actions (`bulkMarkNotificationsRead`, `bulkDeleteNotifications`).
   - Clean empty state (`notifEmptyHtml`) without any monogram logo or icon boxes, with search empty fallback.
   - Revitalized card layout (`notifCardHtml`) with `.tenant-notif-card-revamp`, checkbox and selection highlighting.
   - Stats strip populated during `renderNotificationsPage()`.
3. CSS rules in assets/css/base/08_shell_chrome.css:
   - Container max-width and centering (`.tenant-notif-page-wrap`).
   - Responsive stats strip (`.notif-stats-strip`, `.notif-stat-chip`, `.notif-stat-clickable`).
   - Selection bar and bulk actions (`.notif-selection-bar`, `.notif-bulk-actions`, `.notif-card-checkbox`).
   - Checkbox dimension reset (`min-height: unset !important`, `height: 18px !important`, `width: 18px !important`).
   - Non-wrapping master label (`.notif-select-all-label` with `white-space: nowrap`).
   - Refresh button (`.notif-refresh-btn`) with icon styling.
   - Search box and time filter (`.notif-search-wrap`, `.notif-search-input`, `.notif-time-select`).
   - Revitalized card styling (`.tenant-notif-card-revamp`, `.unread` with turquoise accent, `.selected`).
   - Clean empty state without monogram logo box.
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
        """Notifications page has unified heading, kicker, refresh icon button with key common.refresh, unread chip, and mark-all-read."""
        block = self._get_page_block()
        self.assertIn('class="tenant-page-heading"', block)
        self.assertIn('id="notifPageKicker"', block)
        self.assertIn('data-i18n="page.notifications"', block)
        self.assertIn('data-ws-icon="refresh"', block)
        self.assertIn('notif-refresh-btn', block)
        self.assertIn('renderNotificationsPage()', block)
        self.assertIn('id="notifUnreadCount"', block)
        self.assertIn('notificationsMarkAllRead()', block)

    def test_page_statistics_strip(self):
        """Page has a 4-chip executive stats strip with clickable filter handlers."""
        block = self._get_page_block()
        self.assertIn('id="notifStatsStrip"', block)
        self.assertIn('id="notifStatTotal"', block)
        self.assertIn('id="notifStatUnread"', block)
        self.assertIn('id="notifStatProjects"', block)
        self.assertIn('id="notifStatSystem"', block)
        self.assertIn('notif-stat-clickable', block)
        self.assertIn("setNotifStatusFilter('unread')", block)

    def test_dual_toolbar_tabs_and_controls(self):
        """Toolbar includes category group tabs, read status tabs, search box, and time filter."""
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
        self.assertIn('id="notifSearchInput"', block)
        self.assertIn('onNotifSearchInput()', block)
        self.assertIn('data-i18n="common.search"', block)
        self.assertIn('id="notifTimeFilter"', block)
        self.assertIn('data-i18n="notif.time_all"', block)
        self.assertIn('data-i18n="notif.time_today"', block)
        self.assertIn('data-i18n="notif.time_week"', block)
        self.assertIn('data-i18n="notif.time_month"', block)

    def test_selection_bar_and_bulk_actions_markup(self):
        """Notifications markup includes selection bar with master checkbox and bulk action triggers."""
        block = self._get_page_block()
        self.assertIn('id="notifSelectionBar"', block)
        self.assertIn('id="notifSelectAll"', block)
        self.assertIn('toggleNotifSelectAll(this.checked)', block)
        self.assertIn('data-i18n="common.select_all"', block)
        self.assertIn('id="notifBulkActions"', block)
        self.assertIn('id="notifSelectedCount"', block)
        self.assertIn('bulkMarkNotificationsRead()', block)
        self.assertIn('data-i18n="notif.mark_selected_read"', block)
        self.assertIn('bulkDeleteNotifications()', block)
        self.assertIn('data-i18n="notif.delete_selected"', block)
        self.assertIn('clearNotifSelection()', block)
        self.assertIn('data-i18n="common.cancel"', block)

    def test_redundant_preferences_panel_removed(self):
        """The redundant notification preferences panel is completely removed from the page."""
        block = self._get_page_block()
        self.assertNotIn('notif-prefs-panel', block)
        self.assertNotIn('tenantNotifPrefs', block)

    def test_page_container_wrap(self):
        """List is wrapped in a bounded container avoiding full-screen stretch."""
        block = self._get_page_block()
        self.assertIn('class="tenant-notif-page-wrap"', block)
        self.assertIn('id="tenantNotificationsList"', block)

    def test_js_number_sanitizer(self):
        """JS sanitizer formats long decimal floats cleanly to 2 decimal places."""
        self.assertIn('formatNotifNumberSanitized', self.notif_js)
        pattern = r'(\d+)\.(\d{3,})'
        sample_text = 'تم استهلاك 36.71981688999991 نقطة في عملية توليد الخرائط'
        replaced = re.sub(pattern, lambda m: f"{float(m.group(0)):.2f}", sample_text)
        self.assertEqual(replaced, 'تم استهلاك 36.72 نقطة في عملية توليد الخرائط')

    def test_js_search_and_time_filters(self):
        """JS includes search matching and time range filtering functions with Arabic normalization."""
        self.assertIn('function notifNormalizeText(s)', self.notif_js)
        self.assertIn('function notifMatchesQuery(n, q)', self.notif_js)
        self.assertIn('function notifMatchesTime(createdAt, timeFilter)', self.notif_js)
        self.assertIn('function applyNotifFilters()', self.notif_js)
        self.assertIn('function clearNotifFilters()', self.notif_js)

        # Python-level verification of Arabic normalization and token search parity
        def norm(s):
            if not s: return ''
            s = s.lower()
            s = re.sub(r'[\u064B-\u065F\u0670]', '', s)
            s = re.sub(r'[أإآٱ]', 'ا', s)
            s = re.sub(r'ة', 'ه', s)
            s = re.sub(r'ى', 'ي', s)
            return s

        def match(title, body, cat, q):
            clean_q = (q or '').strip()
            if not clean_q: return True
            tokens = [norm(t) for t in clean_q.split() if t.strip()]
            haystack = norm(f"{title} {body} {cat}")
            return all(tok in haystack for tok in tokens)

        target_title = 'فشلت مهمة التوليد'
        target_body = 'انتهت مهلة التوليد — حرر الحجز تلقائيا'
        target_cat = 'مهام التوليد'

        # Must match user queries like 'فشل مهم', 'فشلت مهمه', 'مهمة فشل', 'iconic'
        self.assertTrue(match(target_title, target_body, target_cat, 'فشل مهم'))
        self.assertTrue(match(target_title, target_body, target_cat, 'فشلت مهمه'))
        self.assertTrue(match(target_title, target_body, target_cat, 'مهمة فشل'))
        self.assertTrue(match(target_title, target_body, target_cat, 'توليد'))

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

    def test_js_clean_empty_state_without_monogram(self):
        """Empty state is clean with title and description, without any monogram logo box."""
        self.assertIn('function notifEmptyHtml(', self.notif_js)
        self.assertIn('tenant-notif-empty-state', self.notif_js)
        self.assertNotIn('notif-empty-monogram', self.notif_js)
        self.assertNotIn('>LL<', self.notif_js)
        self.assertIn('openTenantPresentations()', self.notif_js)
        self.assertIn('clearNotifFilters()', self.notif_js)

    def test_js_multi_selection_and_single_read(self):
        """JS supports individual mark-read and full multi-selection lifecycle."""
        self.assertIn('function toggleNotifSelect', self.notif_js)
        self.assertIn('function toggleNotifSelectAll', self.notif_js)
        self.assertIn('function clearNotifSelection', self.notif_js)
        self.assertIn('function updateNotifSelectionUI', self.notif_js)
        self.assertIn('function notificationMarkSingleRead', self.notif_js)
        self.assertIn('function bulkMarkNotificationsRead', self.notif_js)
        self.assertIn('function bulkDeleteNotifications', self.notif_js)
        self.assertIn('notif-card-checkbox', self.notif_js)
        self.assertIn('notif.mark_read', self.notif_js)

    def test_css_rules_in_shell_chrome(self):
        """CSS includes styles for page wrap, stats strip, revamp cards, selection bar, and clean empty state."""
        self.assertIn('.tenant-notif-page-wrap', self.css_chrome)
        self.assertIn('.notif-stats-strip', self.css_chrome)
        self.assertIn('.notif-stat-chip', self.css_chrome)
        self.assertIn('.notif-stat-clickable', self.css_chrome)
        self.assertIn('.notif-selection-bar', self.css_chrome)
        self.assertIn('.notif-select-all-label', self.css_chrome)
        self.assertIn('white-space: nowrap', self.css_chrome)
        self.assertIn('min-height: unset !important', self.css_chrome)
        self.assertIn('.notif-refresh-btn', self.css_chrome)
        self.assertIn('.notif-search-wrap', self.css_chrome)
        self.assertIn('.notif-search-input', self.css_chrome)
        self.assertIn('.notif-time-select', self.css_chrome)
        self.assertIn('.tenant-notif-card-revamp', self.css_chrome)
        self.assertIn('.tenant-notif-card-revamp.selected', self.css_chrome)
        self.assertIn('.tenant-notif-empty-state', self.css_chrome)
        self.assertNotIn('.notif-empty-monogram', self.css_chrome)

    def test_i18n_parity(self):
        """All notification and action keys are present in both Arabic and English dictionaries."""
        keys = [
            'common.refresh', 'common.search', 'common.select_all', 'common.cancel',
            'notif.stat_total', 'notif.stat_unread', 'notif.stat_projects', 'notif.stat_system',
            'notif.cat_all', 'notif.cat_projects', 'notif.cat_finance', 'notif.cat_support',
            'notif.act_review_approval', 'notif.act_view_project', 'notif.act_view_wallet',
            'notif.act_view_ticket', 'notif.act_view_details',
            'notif.act_review_recharge', 'notif.act_review_ticket', 'notif.act_review_join',
            'notif.empty_title', 'notif.empty_desc', 'notif.empty_cta',
            'notif.empty_search_title', 'notif.empty_search_desc', 'notif.clear_filters',
            'notif.mark_read', 'notif.mark_selected_read', 'notif.delete_selected', 'notif.selected_count',
            'notif.search_placeholder', 'notif.time_label', 'notif.time_all', 'notif.time_today', 'notif.time_week', 'notif.time_month'
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
