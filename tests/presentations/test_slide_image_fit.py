"""Image controls act on the picture, not on its frame.

Uploaded images live in a data-slide-imagebox wrapper. object-fit on a div is
ignored and a radius on the frame does not round the image, so the fit buttons
and the radius field appeared to do nothing.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = ROOT / 'assets' / 'js' / '15b-slide-canvas' / '01_zoom_inspector.js'


def _block(path, name, end):
    source = path.read_text(encoding='utf-8')
    start = source.index('function ' + name)
    stop = source.index(end, start)
    return source[start:stop]


def _client_script():
    return '\n'.join([
        "window.__target = null;",
        "function setSlideSelectionStyle(index, mutator) { mutator(window.__target); }",
        _block(INSPECTOR, 'slideSelectionImageElement', 'function slideToolbarSelectionKind'),
        _block(INSPECTOR, 'setSlideSelectionImageFit', 'function setSlideSelectionBorderRadius'),
        _block(INSPECTOR, 'setSlideSelectionBorderRadius', 'function setSlideSelectionFill'),
    ])


PAGE = """<!doctype html><html dir="rtl"><head><meta charset="utf-8"></head><body>
<div id="box" data-slide-imagebox="1"><img id="inner" style="object-fit:cover;border-radius:10px"></div>
<img id="bare" style="object-fit:cover">
<div id="plain"><img id="plainimg"></div>
<script>__CLIENT__</script>
</body></html>"""


class SlideImageFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page(viewport={'width': 900, 'height': 600})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page.set_content(PAGE.replace('__CLIENT__', _client_script()))

    def test_the_picture_is_resolved_inside_its_frame(self):
        state = self.page.evaluate("""() => ({
            box: slideSelectionImageElement(document.getElementById('box'))?.id || null,
            bare: slideSelectionImageElement(document.getElementById('bare'))?.id || null,
            plain: slideSelectionImageElement(document.getElementById('plain'))?.id || null,
            none: slideSelectionImageElement(null)
        })""")
        self.assertEqual(state, {'box': 'inner', 'bare': 'bare', 'plain': None, 'none': None})

    def test_fit_changes_the_picture_not_the_frame(self):
        state = self.page.evaluate("""() => {
            window.__target = document.getElementById('box');
            setSlideSelectionImageFit(0, 'contain');
            const inner = getComputedStyle(document.getElementById('inner')).objectFit;
            const frame = document.getElementById('box').style.objectFit;
            window.__target = document.getElementById('bare');
            setSlideSelectionImageFit(0, 'contain');
            return {inner, frame, bare: document.getElementById('bare').style.objectFit};
        }""")
        self.assertEqual(state['inner'], 'contain')
        self.assertEqual(state['frame'], '')
        self.assertEqual(state['bare'], 'contain')

    def test_radius_rounds_the_picture_too(self):
        state = self.page.evaluate("""() => {
            window.__target = document.getElementById('box');
            setSlideSelectionBorderRadius(0, 24);
            return {
                frame: document.getElementById('box').style.borderRadius,
                inner: document.getElementById('inner').style.borderRadius
            };
        }""")
        self.assertEqual(state, {'frame': '24px', 'inner': '24px'})


if __name__ == '__main__':
    unittest.main()
