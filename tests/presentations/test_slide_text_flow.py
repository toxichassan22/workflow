"""Text boxes hug their text and leave the flow without moving neighbours.

Generated paragraphs share a flow layout: a fixed height can leave the text
outside its selection frame, and resizing one paragraph reflows the following
ones. The first geometry touch lifts the paragraph into an absolute box with an
invisible placeholder keeping its slot.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / 'assets' / 'js' / '14-slides-gen' / '02_element_editing.js'


def _block(path, name, end):
    source = path.read_text(encoding='utf-8')
    start = source.index('function ' + name)
    stop = source.index(end, start)
    return source[start:stop]


def _client_script():
    return '\n'.join([
        "function slideRenderedScale() { return 1; }",
        _block(ELEMENTS, 'slideTextNeedsContentHeight', 'function slideTextContentHeight'),
        _block(ELEMENTS, 'slideTextContentHeight', 'function slideFlowPlaceholder'),
        _block(ELEMENTS, 'slideFlowPlaceholder', 'function slideDetachInfo'),
        _block(ELEMENTS, 'slideDetachInfo', 'function applySlideDetachedElement'),
        _block(ELEMENTS, 'applySlideDetachedElement', 'function detachSlideTextElementLive'),
        _block(ELEMENTS, 'detachSlideTextElementLive', 'function fitSlideTextElement'),
    ])


LONG_TEXT = ' '.join(['نص طويل لاختبار ارتفاع المحتوى داخل الفقرة'] * 6)

PAGE = """<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<style>body { margin: 0; } p { margin: 0 0 18px; font-size: 13px; line-height: 2; }</style>
</head><body>
<div class="tenant-slide-stage">
  <div class="slide" style="width:1280px;height:720px;position:relative;overflow:hidden;">
    <div id="column" style="width:390px;padding:8px 0 0 20px;box-sizing:border-box;">
      <p id="target" style="min-height:57px;height:57px;overflow:visible;">LONG</p>
      <p id="following">الفقرة التالية</p>
    </div>
    <div id="right" style="position:absolute;top:0;left:0;width:390px;">العمود الأيمن</div>
  </div>
</div>
<table><tbody><tr><td id="cell">خلية</td></tr></tbody></table>
<script>__CLIENT__</script>
</body></html>"""


class SlideTextFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page(viewport={'width': 1400, 'height': 900})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page.set_content(PAGE.replace('LONG', LONG_TEXT).replace('__CLIENT__', _client_script()))

    def test_content_height_exceeds_a_fixed_box(self):
        state = self.page.evaluate("""() => ({
            needed: slideTextContentHeight(document.getElementById('target')),
            fixed: 57,
            p: slideTextNeedsContentHeight(document.getElementById('target')),
            cell: slideTextNeedsContentHeight(document.getElementById('cell'))
        })""")
        self.assertGreater(state['needed'], state['fixed'])
        self.assertTrue(state['p'])
        self.assertFalse(state['cell'])

    def test_detach_keeps_the_following_paragraph_in_place(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const following = document.getElementById('following');
            const rel = () => Math.round(following.getBoundingClientRect().top - slide.getBoundingClientRect().top);
            const before = rel();
            const info = detachSlideTextElementLive(stage, target);
            return {
                info: !!info,
                absolute: getComputedStyle(target).position,
                insideSlide: target.parentElement === slide,
                placeholders: slide.querySelectorAll('[data-slide-flow-placeholder]').length,
                before,
                after: rel()
            };
        }""")
        self.assertTrue(state['info'])
        self.assertEqual(state['absolute'], 'absolute')
        self.assertTrue(state['insideSlide'])
        self.assertEqual(state['placeholders'], 1)
        self.assertLessEqual(abs(state['after'] - state['before']), 1)

    def test_placeholder_owns_the_freed_slot(self):
        state = self.page.evaluate("""() => {
            const ph = slideFlowPlaceholder(document, {
                layoutWidth: 390, layoutHeight: 57,
                margins: { top: '0px', right: '0px', bottom: '18px', left: '0px' },
                flex: '0 1 auto', alignSelf: 'auto', order: '0'
            });
            return {
                attr: ph.getAttribute('data-slide-flow-placeholder'),
                hidden: ph.style.visibility,
                width: ph.style.width,
                height: ph.style.height,
                margin: ph.style.margin
            };
        }""")
        self.assertEqual(state['attr'], '1')
        self.assertEqual(state['hidden'], 'hidden')
        self.assertEqual(state['width'], '390px')
        self.assertEqual(state['height'], '57px')
        self.assertIn('18px', state['margin'])
        self.assertTrue(state['margin'].startswith('0px'))


if __name__ == '__main__':
    unittest.main()
