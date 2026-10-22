"""Injected market pages must start directly under the header.

The market frame used to center its content vertically (`safe center`). A short
page therefore opened with a gap far taller than the 56px header, and a taller
one ran past the footer. The frame now starts the content at the top of its
safe lane; this test measures the real rendered layout in Chromium.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HEADER = (
    '<header class="slide-header" data-slide-header="1" dir="rtl" '
    'style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;z-index:10;">'
    '<span>نطاق الدراسة</span></header>'
)
FOOTER = (
    '<footer class="slide-footer" data-slide-footer="1" dir="rtl" '
    'style="position:absolute;bottom:0;right:0;left:0;height:36px;background:#123B6D;z-index:10;">'
    '<span data-slide-counter="1" dir="ltr">03 — 09</span></footer>'
)


class SlideSafeAreaUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        import slide_engine
        cls.engine = slide_engine
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def _market_slide(self):
        body = (
            '<main style="margin-top:56px;padding:20px 24px;">'
            '<h2 style="margin:0 0 12px;font-size:26px;">النطاق الجغرافي للمشروع</h2>'
            '<p style="margin:0;font-size:15px;line-height:1.8;">نص قصير يوضح نطاق الدراسة.</p>'
            '</main>'
        )
        return (
            '<div class="slide" dir="rtl" '
            'style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;">'
            + HEADER + body + FOOTER + '</div>'
        )

    def _measure(self, html):
        self.page.set_content(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<style>body{margin:0}</style></head><body>' + html + '</body></html>')
        return self.page.evaluate(
            """() => {
                   const slide = document.querySelector('.slide');
                   const header = slide.querySelector('[data-slide-header]');
                   const footer = slide.querySelector('[data-slide-footer]');
                   let top = Infinity;
                   let bottom = -Infinity;
                   slide.querySelectorAll('h2,p').forEach(el => {
                       const rect = el.getBoundingClientRect();
                       if (rect.height < 2) return;
                       top = Math.min(top, rect.top);
                       bottom = Math.max(bottom, rect.bottom);
                   });
                   return {
                       top: Math.round(top),
                       bottom: Math.round(bottom),
                       headerBottom: Math.round(header.getBoundingClientRect().bottom),
                       footerTop: Math.round(footer.getBoundingClientRect().top),
                   };
               }""")

    def test_a_stored_market_frame_is_top_aligned_on_renumber(self):
        # Older decks stored the same frame with `safe center` and the stripped
        # header's 56px margin still on the first block; the preview and export
        # must both open at the top of the lane after a renumber.
        stored = self.engine._normalize_market_content_layout(
            self._market_slide(), slide_type='content',
            slide_title='نطاق الدراسة', content_source='market_study_data.scope')
        stored = stored.replace('justify-content:flex-start', 'justify-content:safe center')
        slides = [
            {'title': 'نطاق الدراسة', 'type': 'content', 'section_key': 'market',
             'content_source': 'market_study_data.scope', 'html': stored},
            {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'},
        ]
        renumbered = self.engine.renumber_presentation_slides(
            slides, branding={}, project_data={'project_name': 'مشروع الاختبار'})
        html = renumbered[0]['html']
        self.assertIn('justify-content:flex-start', html)
        self.assertNotIn('safe center', html)
        metrics = self._measure(html)
        self.assertLessEqual(metrics['top'] - metrics['headerBottom'], 40, metrics)
        self.assertLess(metrics['bottom'], metrics['footerTop'], metrics)

    def test_the_preview_mirrors_the_market_frame_spacing(self):
        source = (ROOT / 'assets' / 'js' / '13-visual' / '02_slides_progress.js').read_text(
            encoding='utf-8')
        start = source.index('function stripReservedSlideHeaderSpacing')
        end = source.index('function processSlideHtmlClient')
        self.page.add_script_tag(content=source[start:end])
        stored = self.engine._normalize_market_content_layout(
            self._market_slide(), slide_type='content',
            slide_title='نطاق الدراسة', content_source='market_study_data.scope')
        stored = stored.replace('justify-content:flex-start', 'justify-content:safe center')
        cleaned = self.page.evaluate(
            '(html) => normalizeMarketFrameSpacing(html)', stored)
        self.assertIn('justify-content:flex-start', cleaned)
        self.assertNotIn('safe center', cleaned)
        self.assertIn('margin-top:0!important', cleaned)

    def test_the_market_frame_starts_its_content_at_the_top_of_the_safe_lane(self):
        normalized = self.engine._normalize_market_content_layout(
            self._market_slide(), slide_type='content',
            slide_title='نطاق الدراسة', content_source='market_study_data.scope')
        self.assertIn('justify-content:flex-start', normalized)
        self.assertNotIn('safe center', normalized)

        metrics = self._measure(normalized)
        # The header owns the first 56px; the content starts at the top of the
        # padded lane (64px) instead of being centered hundreds of pixels down.
        self.assertLessEqual(metrics['top'] - metrics['headerBottom'], 40, metrics)
        self.assertLess(metrics['bottom'], metrics['footerTop'], metrics)


if __name__ == '__main__':
    unittest.main()
