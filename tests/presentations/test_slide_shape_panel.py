"""The shape panel reads the element it edits.

The shape tab shipped fixed markup values (white fill, no border, zero
thickness and corners) and rebuilt itself from those defaults after every
change, so the corner counter snapped back while the element kept the radius.
This suite runs the real snapshot helpers in Chromium.
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
        "function cssColorToHex(value) {",
        "  const text = String(value || '').trim().toLowerCase();",
        "  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);",
        "  if (hex) {",
        "    let digits = hex[1];",
        "    if (digits.length === 3) digits = digits.split('').map(ch => ch + ch).join('');",
        "    return '#' + digits;",
        "  }",
        "  const rgb = text.match(/^rgba?\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})(?:\\s*,\\s*([\\d.]+))?\\s*\\)$/);",
        "  if (!rgb) return '';",
        "  if (rgb[4] !== undefined && Number(rgb[4]) === 0) return '';",
        "  return '#' + [rgb[1], rgb[2], rgb[3]].map(n => Number(n).toString(16).padStart(2, '0')).join('');",
        "}",
        _block(INSPECTOR, 'slideElementInlineValue', 'function slideStyleNumber'),
        _block(INSPECTOR, 'slideStyleNumber', 'function slideRadiusPx'),
        _block(INSPECTOR, 'slideRadiusPx', '/* The shape panel shows'),
        _block(INSPECTOR, 'slideShapeStyleSnapshot', 'function slideShapeToolbarSnapshot'),
    ])


PAGE = """<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<style>body { margin: 0; } div { box-sizing: border-box; }</style></head><body>
<div id="branded" style="width:200px;height:120px;background:rgb(180, 90, 27);
  border:6px solid #112233;border-radius:30px;"></div>
<div id="circle" style="width:200px;height:200px;background:#07182C;border-radius:50%;"></div>
<div id="plain" style="width:100px;height:100px;"></div>
<script>__CLIENT__</script>
</body></html>"""


class SlideShapePanelTests(unittest.TestCase):
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

    def test_snapshot_reads_fill_border_and_corners(self):
        state = self.page.evaluate("""() => slideShapeStyleSnapshot(
            document.getElementById('branded'))""")
        self.assertEqual(state, {
            'fill': '#b45a1b', 'borderColor': '#112233', 'borderWidth': 6, 'radius': 30
        })

    def test_a_percentage_corner_is_shown_as_its_px(self):
        state = self.page.evaluate("""() => slideShapeStyleSnapshot(
            document.getElementById('circle'))""")
        self.assertEqual(state['radius'], 100)
        self.assertEqual(state['fill'], '#07182c')
        self.assertEqual(state['borderWidth'], 0)

    def test_a_plain_element_falls_back_to_the_panel_defaults(self):
        state = self.page.evaluate("""() => slideShapeStyleSnapshot(
            document.getElementById('plain'))""")
        self.assertEqual(state['fill'], '#ffffff')
        self.assertEqual(state['borderWidth'], 0)
        self.assertEqual(state['radius'], 0)

    def test_no_element_returns_the_defaults(self):
        state = self.page.evaluate("""() => slideShapeStyleSnapshot(null)""")
        self.assertEqual(state, {
            'fill': '#ffffff', 'borderColor': '#dbe3ea', 'borderWidth': 0, 'radius': 0
        })


if __name__ == '__main__':
    unittest.main()
