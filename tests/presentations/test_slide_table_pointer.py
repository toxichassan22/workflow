"""A table is one shape for the pointer; its cells open on a tap once selected.

Generated decks carry bare <table> elements, not the manual authoring wrapper.
They used to enter inline text editing cell by cell, so a single click never
selected the table. This suite runs the real client helpers in Chromium and
checks the generated-table path, the single-tap cell edit, the drag threshold,
the real style snapshot behind the border counter and whole-table alignment.
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


def _tail(path, name):
    source = path.read_text(encoding='utf-8')
    return source[source.index('function ' + name):]


def _client_script():
    return '\n'.join([
        "var slideInlineEditStates = {0: true};",
        "var slideElementEditStates = {0: true};",
        "var slideEditSessions = {0: {}};",
        "var slideElementDragActive = false;",
        "window.__editedCell = null;",
        "window.__marqueeStarted = false;",
        "function hasPermission() { return true; }",
        "function autoFitSlideContent() {}",
        "function getSlideEditSession(index) { return slideEditSessions[index] || null; }",
        "function beginSlideTableCellEdit(stage, index, cell) { window.__editedCell = cell; }",
        "function slidePathIgnores() { return false; }",
        "function slideChromeOf() { return null; }",
        "function watermarkOverlayOf() { return null; }",
        "function slideNodeIsVisualShape() { return false; }",
        "function slideElementPath() { return [0]; }",
        "function canvasSession() { return {}; }",
        "function startSlideMarqueeSelection() { window.__marqueeStarted = true; }",
        "function clearSlideSnapGuides() {}",
        "function stopEditEvent() {}",
        "function onInlineEditKey() {}",
        "function onInlineEditPaste() {}",
        "function onSlideEditableFocus() {}",
        "function commitSlideInlineEdit() {}",
        "function slideRenderedScale() { return 1; }",
        "function selectSlideElement() { window.__selected = true; }",
        "function commitSlideElementMove(stage, index, target, path, dx, dy) { window.__movedBy = { dx: dx, dy: dy }; }",
        "function WFT(key, fallback) { return fallback; }",
        "function toast() {}",
        "Element.prototype.setPointerCapture = function() {};",
        "Element.prototype.releasePointerCapture = function() {};",
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
        "function slideTableCellAt(table, row, col) {",
        "  const line = table && table.rows && table.rows[row];",
        "  return line ? line.cells[col] || null : null;",
        "}",
        _block(SLIDE_PROGRESS, 'collectSlideTextNodes', 'function markSlideTablesForPointerEditing'),
        _block(SLIDE_PROGRESS, 'markSlideTablesForPointerEditing', 'function slidePathIgnores'),
        _block(AUTHORING, 'slideTableStyleSnapshot', 'function slideTableToolbarSnapshot'),
        _block(AUTHORING, 'setSlideTableTextAlign', 'function runSlideTableAction'),
        _block(AUTHORING, 'bindSlideTableEditing', 'function beginSlideTableCellEdit'),
        _block(ELEMENT_DRAG, 'slideDragTarget', 'function findSlideRawTarget'),
        _tail(ELEMENT_DRAG, 'enableSlideElementDragging'),
    ])


PAGE = """<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<style>
  body { margin: 0; }
  #tenantSlidesMain { height: 900px; overflow: auto; }
  #slide-card-0 { width: 640px; }
  .tenant-slide-stage { width: 640px; height: 360px; position: relative; overflow: hidden; }
  .slide { width: 1280px; height: 720px; position: relative; transform: scale(.5); transform-origin: 0 0; }
  table { width: 100%; border-collapse: collapse; }
  #table-frame { width: 600px; margin: 50px 40px 0; overflow: hidden; }
  #bare-table { width: 300px; margin: 20px 40px; }
  td, th { height: 50px; border: 1px solid #ccc; }
  .slide-inline-inspector { height: 80px; background: #eef; }
</style></head><body>
<div id="tenantSlidesMain">
  <div id="slide-card-0" class="ge-slide-card">
    <div class="tenant-slide-stage">
      <div class="slide">
        <p id="body-copy">نص عادي</p>
        <span id="editable-text" contenteditable="plaintext-only">نص قابل للتعديل</span>
        <div id="table-frame">
          <div id="table-title">جدول بنود التكلفة</div>
          <table id="generated-table"><thead><tr><th>المرحلة</th><th>المدة</th></tr></thead>
          <tbody><tr><td id="cell-a">التصميم</td><td>6 أشهر</td></tr></tbody></table>
        </div>
        <table id="bare-table"><tbody><tr><td id="bare-cell">خلية مستقلة</td></tr></tbody></table>
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

    def test_generated_table_frame_is_the_pointer_shape(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            enableSlideInlineEditing(stage, 0);
            const frame = document.getElementById('table-frame');
            const table = document.getElementById('generated-table');
            const bare = document.getElementById('bare-table');
            const cell = document.getElementById('cell-a');
            const copy = document.getElementById('body-copy');
            const title = document.getElementById('table-title');
            const slide = document.querySelector('.slide');
            return {
                frameMarked: frame.getAttribute('data-slide-table'),
                tableMarked: table.getAttribute('data-slide-table'),
                bareMarked: bare.getAttribute('data-slide-table'),
                cellEditable: cell.getAttribute('contenteditable'),
                copyEditable: copy.getAttribute('contenteditable'),
                titleEditable: title.getAttribute('contenteditable'),
                frameTarget: slideDragTarget(slide, cell)?.id || '',
                bareTarget: slideDragTarget(slide, document.getElementById('bare-cell'))?.id || '',
                bound: document.getElementById('slide-card-0').dataset.tableEditingBound,
            };
        }""")
        self.assertEqual(state['frameMarked'], '1')
        self.assertIsNone(state['tableMarked'])
        self.assertEqual(state['bareMarked'], '1')
        self.assertIsNone(state['cellEditable'])
        self.assertEqual(state['copyEditable'], 'plaintext-only')
        self.assertEqual(state['titleEditable'], 'plaintext-only')
        self.assertEqual(state['frameTarget'], 'table-frame')
        self.assertEqual(state['bareTarget'], 'bare-table')
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
            const frame = document.getElementById('table-frame');
            const cell = document.getElementById('cell-a');
            enableSlideInlineEditing(stage, 0);
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, pointerId: 1,
                clientX: 0, clientY: 0
            }));
            frame.dispatchEvent(new MouseEvent('dblclick', {
                bubbles: true, cancelable: true, clientX: 0, clientY: 0
            }));
            return window.__editedCell?.id || '';
        }""")
        self.assertEqual(edited, 'cell-a')

    def test_contenteditable_text_keeps_native_pointer_behavior(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const text = document.getElementById('editable-text');
            enableSlideElementDragging(stage, 0);
            const rect = text.getBoundingClientRect();
            const event = new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, button: 0,
                clientX: rect.left + 5, clientY: rect.top + 5
            });
            text.dispatchEvent(event);
            return {
                prevented: event.defaultPrevented,
                marquee: window.__marqueeStarted
            };
        }""")
        self.assertFalse(state['prevented'])
        self.assertFalse(state['marquee'])

    def test_a_single_tap_inside_the_selected_table_opens_the_cell(self):
        edited = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const frame = document.getElementById('table-frame');
            const cell = document.getElementById('cell-a');
            enableSlideInlineEditing(stage, 0);
            frame.classList.add('slide-element-selected');
            const rect = cell.getBoundingClientRect();
            const point = { clientX: rect.left + 20, clientY: rect.top + 20 };
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1, ...point
            }));
            cell.dispatchEvent(new PointerEvent('pointerup', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1, ...point
            }));
            return window.__editedCell?.id || '';
        }""")
        self.assertEqual(edited, 'cell-a')

    def test_a_tap_that_moved_does_not_open_the_cell(self):
        edited = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const frame = document.getElementById('table-frame');
            const cell = document.getElementById('cell-a');
            enableSlideInlineEditing(stage, 0);
            frame.classList.add('slide-element-selected');
            const rect = cell.getBoundingClientRect();
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: rect.left + 20, clientY: rect.top + 20
            }));
            cell.dispatchEvent(new PointerEvent('pointerup', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: rect.left + 80, clientY: rect.top + 20
            }));
            return window.__editedCell?.id || '';
        }""")
        self.assertEqual(edited, '')

    def test_a_jittery_click_does_not_nudge_the_table(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const table = document.getElementById('bare-table');
            const cell = document.getElementById('bare-cell');
            enableSlideInlineEditing(stage, 0);
            enableSlideElementDragging(stage, 0);
            const rect = cell.getBoundingClientRect();
            const start = { clientX: rect.left + 5, clientY: rect.top + 5 };
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1, ...start
            }));
            table.dispatchEvent(new PointerEvent('pointermove', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: start.clientX + 3, clientY: start.clientY
            }));
            table.dispatchEvent(new PointerEvent('pointerup', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: start.clientX + 3, clientY: start.clientY
            }));
            return { transform: table.style.transform, movedBy: window.__movedBy || null };
        }""")
        self.assertEqual(state['transform'], '')
        self.assertIsNone(state['movedBy'])

    def test_a_real_drag_still_moves_the_table(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const table = document.getElementById('bare-table');
            const cell = document.getElementById('bare-cell');
            enableSlideInlineEditing(stage, 0);
            enableSlideElementDragging(stage, 0);
            const rect = cell.getBoundingClientRect();
            const start = { clientX: rect.left + 5, clientY: rect.top + 5 };
            cell.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1, ...start
            }));
            table.dispatchEvent(new PointerEvent('pointermove', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: start.clientX + 24, clientY: start.clientY
            }));
            table.dispatchEvent(new PointerEvent('pointerup', {
                bubbles: true, cancelable: true, button: 0, pointerId: 1,
                clientX: start.clientX + 24, clientY: start.clientY
            }));
            return { transform: table.style.transform, movedBy: window.__movedBy || null };
        }""")
        self.assertIn('translate(24px, 0px)', state['transform'])
        self.assertIsNotNone(state['movedBy'])
        self.assertAlmostEqual(state['movedBy']['dx'], 24, delta=1)

    def test_table_text_alignment_applies_to_every_cell(self):
        result = self.page.evaluate("""() => {
            const live = document.getElementById('generated-table');
            const raw = live.cloneNode(true);
            setSlideTableTextAlign(live, raw, 'center');
            const read = table => Array.from(table.querySelectorAll('td, th'))
                .map(cell => cell.style.textAlign);
            return { live: read(live), raw: read(raw) };
        }""")
        self.assertTrue(result['live'])
        self.assertEqual(set(result['live']), {'center'})
        self.assertEqual(set(result['raw']), {'center'})

    def test_table_style_snapshot_reads_the_real_cell(self):
        state = self.page.evaluate("""() => {
            const table = document.getElementById('generated-table');
            const cell = document.getElementById('cell-a');
            cell.style.borderTopWidth = '6px';
            cell.style.borderTopStyle = 'solid';
            cell.style.borderTopColor = '#112233';
            cell.style.backgroundColor = '#ffeeaa';
            const styled = slideTableStyleSnapshot(table, cell);
            const plain = slideTableStyleSnapshot(table, table.querySelector('th'));
            return { styled, plain };
        }""")
        self.assertEqual(state['styled'], {
            'width': 6, 'borderColor': '#112233', 'cellFill': '#ffeeaa'
        })
        self.assertEqual(state['plain'], {
            'width': 1, 'borderColor': '#cccccc', 'cellFill': '#ffffff'
        })


if __name__ == '__main__':
    unittest.main()
