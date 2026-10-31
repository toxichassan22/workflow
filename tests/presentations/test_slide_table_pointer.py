"""A table is one shape for the pointer; only a double-click enters one cell.

Generated decks carry bare <table> elements, not the manual authoring wrapper.
They used to enter inline text editing cell by cell, so a single click never
selected the table. This suite runs the real client helpers in Chromium and
checks the generated-table path, including the retargeted double-click after the
selection controls move the canvas.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLIDE_PROGRESS = ROOT / 'assets' / 'js' / '13-visual' / '02_slides_progress.js'
AUTHORING = ROOT / 'assets' / 'js' / '15b-slide-canvas' / '04_authoring.js'
ELEMENT_DRAG = ROOT / 'assets' / 'js' / '13-visual' / '02a_slide_element_drag.js'


def _block(path, name, end):
    source = path.read_text(encoding='utf-8')
    start = source.index('function ' + name)
    stop = source.index(end, start)
    return source[start:stop]


def _client_script():
    return '\n'.join([
        "var slideInlineEditStates = {0: true};",
        "var slideElementEditStates = {0: true};",
        "var slideEditSessions = {0: {}};",
        "window.__editedCell = null;",
        "function hasPermission() { return true; }",
        "function autoFitSlideContent() {}",
        "function getSlideEditSession(index) { return slideEditSessions[index] || null; }",
        "function beginSlideTableCellEdit(stage, index, cell) { window.__editedCell = cell; }",
        "function slidePathIgnores() { return false; }",
        "function slideChromeOf() { return null; }",
        "function watermarkOverlayOf() { return null; }",
        "function slideNodeIsVisualShape() { return false; }",
        "function stopEditEvent() {}",
        "function onInlineEditKey() {}",
        "function onInlineEditPaste() {}",
        "function onSlideEditableFocus() {}",
        "function commitSlideInlineEdit() {}",
        "function slideTableCellAt(table, row, col) {",
        "  const line = table && table.rows && table.rows[row];",
        "  return line ? line.cells[col] || null : null;",
        "}",
        _block(SLIDE_PROGRESS, 'collectSlideTextNodes', 'function markSlideTablesForPointerEditing'),
        _block(SLIDE_PROGRESS, 'markSlideTablesForPointerEditing', 'function slidePathIgnores'),
        _block(AUTHORING, 'bindSlideTableEditing', 'function beginSlideTableCellEdit'),
        _block(ELEMENT_DRAG, 'slideDragTarget', 'function findSlideRawTarget'),
    ])


PAGE = """<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<style>
  body { margin: 0; }
  #tenantSlidesMain { height: 900px; overflow: auto; }
  #slide-card-0 { width: 640px; }
  .tenant-slide-stage { width: 640px; height: 360px; position: relative; overflow: hidden; }
  .slide { width: 1280px; height: 720px; position: relative; transform: scale(.5); transform-origin: 0 0; }
  table { width: 600px; margin: 80px 40px; border-collapse: collapse; }
  td, th { height: 50px; border: 1px solid #ccc; }
  .slide-inline-inspector { height: 80px; background: #eef; }
</style></head><body>
<div id="tenantSlidesMain">
  <div id="slide-card-0" class="ge-slide-card">
    <div class="tenant-slide-stage">
      <div class="slide">
        <p id="body-copy">نص عادي</p>
        <table id="generated-table"><thead><tr><th>المرحلة</th><th>المدة</th></tr></thead>
        <tbody><tr><td id="cell-a">التصميم</td><td>6 أشهر</td></tr></tbody></table>
      </div>
    </div>
    <div id="inspector" class="slide-inline-inspector"></div>
  </div>
</div>
<script>__CLIENT__</script>
</body></html>"""


class SlideTablePointerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page(viewport={'width': 1200, 'height': 900})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page.set_content(PAGE.replace('__CLIENT__', _client_script()))

    def test_generated_table_is_marked_and_skips_cell_inline_editing(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            enableSlideInlineEditing(stage, 0);
            const table = document.getElementById('generated-table');
            const cell = document.getElementById('cell-a');
            const copy = document.getElementById('body-copy');
            const slide = document.querySelector('.slide');
            return {
                marked: table.getAttribute('data-slide-table'),
                cellEditable: cell.getAttribute('contenteditable'),
                copyEditable: copy.getAttribute('contenteditable'),
                dragTarget: slideDragTarget(slide, cell)?.id || '',
                bound: document.getElementById('slide-card-0').dataset.tableEditingBound,
            };
        }""")
        self.assertEqual(state['marked'], '1')
        self.assertIsNone(state['cellEditable'])
        self.assertEqual(state['copyEditable'], 'plaintext-only')
        self.assertEqual(state['dragTarget'], 'generated-table')
        self.assertEqual(state['bound'], '1')

    def test_the_second_tap_opens_the_recorded_cell_after_controls_shift_the_page(self):
        edited = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const cell = document.getElementById('cell-a');
            const inspector = document.getElementById('inspector');
            enableSlideInlineEditing(stage, 0);
            const rect = cell.getBoundingClientRect();
            const point = { clientX: rect.left + 20, clientY: rect.top + 20 };
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, pointerId: 1, ...point
            }));
            inspector.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, pointerId: 2, ...point
            }));
            return window.__editedCell?.id || '';
        }""")
        self.assertEqual(edited, 'cell-a')

    def test_a_retargeted_double_click_resolves_a_cell_from_the_table(self):
        edited = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const table = document.getElementById('generated-table');
            const cell = document.getElementById('cell-a');
            enableSlideInlineEditing(stage, 0);
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, pointerId: 1,
                clientX: 0, clientY: 0
            }));
            table.dispatchEvent(new MouseEvent('dblclick', {
                bubbles: true, cancelable: true, clientX: 0, clientY: 0
            }));
            return window.__editedCell?.id || '';
        }""")
        self.assertEqual(edited, 'cell-a')


if __name__ == '__main__':
    unittest.main()
