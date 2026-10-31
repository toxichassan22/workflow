"""The index slide keeps its two-column design after a delete or a refresh.

The client mirrors the server renumbering. It used to update the index rows in
place, so removing a section could leave every remaining row piled into the
first column while the second stayed empty. These cases run the real browser
functions against a collapsed index and check the layout, not just the text.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLIDE_SCRIPT = ROOT / 'assets' / 'js' / '13-visual' / '02_slides_progress.js'


def _row(key, title, page):
    return (
        f'<div data-index-section="{key}" style="min-height:48px;">'
        f'<div>{title}</div>'
        f'<div data-index-page="{key}" dir="ltr">{page}</div></div>'
    )


COLLAPSED_INDEX = (
    '<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
    '<div style="display:grid;grid-template-columns:1fr 1fr;">'
    '<div>'
    + _row('overview', 'نبذة عن المشروع', '03')
    + _row('land', 'بيانات الأرض', '04')
    + _row('location', 'موقع المشروع', '05')
    + '</div><div></div></div></div>'
)


class PresentationIndexUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        source = SLIDE_SCRIPT.read_text(encoding='utf-8')
        start = source.index('function buildTenantIndexSlideHtml')
        end = source.index('function renumberTenantSlides')
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page()
        cls.page.set_content('<!doctype html><html><body></body></html>')
        cls.page.add_script_tag(content=source[start:end])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def _renumber(self, entries):
        return self.page.evaluate(
            """({ html, entries, index, total }) => {
                   const result = renumberTenantSlideHtml(
                       { html, type: 'index' }, index, total, entries);
                   const template = document.createElement('template');
                   template.innerHTML = result;
                   const root = template.content.querySelector('.slide');
                   const firstRow = root.querySelector('[data-index-section]');
                   const grid = firstRow?.parentElement?.parentElement || null;
                   const columns = grid
                       ? Array.from(grid.children).map(
                             column => column.querySelectorAll('[data-index-section]').length)
                       : [];
                   return { html: result, columns };
               }""",
            {'html': COLLAPSED_INDEX, 'entries': entries, 'index': 2, 'total': 6},
        )

    def test_a_collapsed_index_is_redistributed_after_renumbering(self):
        entries = [
            {'section_key': 'overview', 'title': 'نبذة عن المشروع', 'page': 3},
            {'section_key': 'land', 'title': 'بيانات الأرض', 'page': 4},
            {'section_key': 'location', 'title': 'موقع المشروع', 'page': 5},
            {'section_key': 'closing', 'title': 'الخاتمة', 'page': 6},
        ]
        result = self._renumber(entries)
        html = result['html']
        self.assertEqual(html.count('data-index-section='), 4)
        self.assertEqual(result['columns'], [2, 2])
        for entry in entries:
            self.assertRegex(
                html, rf'data-index-page="{entry["section_key"]}"[^>]*>{entry["page"]:02d}')

    def test_a_deleted_section_leaves_a_balanced_index(self):
        entries = [
            {'section_key': 'overview', 'title': 'نبذة عن المشروع', 'page': 3},
            {'section_key': 'location', 'title': 'موقع المشروع', 'page': 4},
            {'section_key': 'closing', 'title': 'الخاتمة', 'page': 5},
        ]
        result = self._renumber(entries)
        html = result['html']
        self.assertEqual(html.count('data-index-section='), 3)
        self.assertNotIn('data-index-section="land"', html)
        self.assertEqual(result['columns'], [2, 1])
        self.assertRegex(html, r'data-index-page="location"[^>]*>04')

    def test_a_new_section_receives_a_designed_row(self):
        entries = [
            {'section_key': 'overview', 'title': 'نبذة عن المشروع', 'page': 3},
            {'section_key': 'land', 'title': 'بيانات الأرض', 'page': 4},
            {'section_key': 'location', 'title': 'موقع المشروع', 'page': 5},
            {'section_key': 'team', 'title': 'فريق العمل', 'page': 6},
            {'section_key': 'closing', 'title': 'الخاتمة', 'page': 7},
        ]
        result = self._renumber(entries)
        html = result['html']
        self.assertEqual(html.count('data-index-section='), 5)
        self.assertEqual(result['columns'], [3, 2])
        self.assertIn('data-index-section="team"', html)
        self.assertRegex(html, r'data-index-page="team"[^>]*>06')
        self.assertIn('فريق العمل', html)

    def test_a_designer_edited_index_keeps_its_own_layout(self):
        designed = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'background:#0b1f33;color:#ffffff;">'
            '<div class="client-index-heading">CLIENT-INDEX-DESIGN</div>'
            '<div class="client-index-list">'
            + _row('overview', 'نبذة موسعة', '03')
            + _row('land', 'الأرض', '04')
            + '</div></div>'
        )
        html = self.page.evaluate(
            """({ html, entries }) => renumberTenantSlideHtml(
                   { html, type: 'index', is_custom: true, _designer_keep_html: true },
                   2, 6, entries)""",
            {'html': designed, 'entries': [
                {'section_key': 'overview', 'title': 'نبذة موسعة', 'page': 5},
                {'section_key': 'land', 'title': 'الأرض', 'page': 6},
            ]},
        )
        # The layout, heading and row markup survive the renumber pass.
        self.assertIn('CLIENT-INDEX-DESIGN', html)
        self.assertIn('client-index-list', html)
        self.assertIn('نبذة موسعة', html)
        self.assertNotIn('grid-template-columns:1fr 1fr', html)
        # Only the page labels follow the deck positions.
        self.assertRegex(html, r'data-index-page="overview"[^>]*>05')
        self.assertRegex(html, r'data-index-page="land"[^>]*>06')

    def test_a_designer_edited_index_without_rows_is_never_replaced(self):
        free_design = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
            '<div class="free-index-design">FREE-INDEX</div></div>'
        )
        html = self.page.evaluate(
            """({ html, entries }) => renumberTenantSlideHtml(
                   { html, type: 'index', is_custom: true }, 2, 6, entries)""",
            {'html': free_design, 'entries': [
                {'section_key': 'overview', 'title': 'نبذة عن المشروع', 'page': 3},
            ]},
        )
        self.assertIn('FREE-INDEX', html)
        self.assertNotIn('data-index-section="overview"', html)


if __name__ == '__main__':
    unittest.main()
