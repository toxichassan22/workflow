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
        _block(ELEMENTS, 'slideTextContentHeight', 'function slideTextVisualCenterY'),
        _block(ELEMENTS, 'slideTextVisualCenterY', 'function slideTextBoxNeedsFit'),
        _block(ELEMENTS, 'slideTextBoxNeedsFit', 'function slideFlowPlaceholder'),
        _block(ELEMENTS, 'slideFlowPlaceholder', 'function removeSlideFlowPlaceholders'),
        _block(ELEMENTS, 'removeSlideFlowPlaceholders', 'function stripSlideFlowOwners'),
        _block(ELEMENTS, 'stripSlideFlowOwners', 'function releaseSlideFlowSlot'),
        _block(ELEMENTS, 'releaseSlideFlowSlot', 'function slideDetachInfo'),
        _block(ELEMENTS, 'slideDetachInfo', 'function applySlideDetachedElement'),
        _block(ELEMENTS, 'applySlideDetachedElement', 'function detachSlideTextElementLive'),
        _block(ELEMENTS, 'detachSlideTextElementLive', 'function fitSlideTextPair'),
        _block(ELEMENTS, 'fitSlideTextPair', 'function fitSlideTextElement'),
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
    <div id="row" style="position:absolute;top:360px;right:0;width:390px;display:flex;align-items:stretch;">
      <p id="stretched" style="margin:0;width:200px;">سطر قصير</p>
      <div style="width:100px;height:180px;"></div>
    </div>
    <div id="centeredBox" data-slide-textbox="1" style="position:absolute;top:560px;right:0;width:300px;height:200px;display:flex;align-items:center;justify-content:center;overflow:visible;">نص قصير داخل صندوق مرتفع</div>
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

    def test_a_stretched_flex_item_measures_its_words_not_its_row(self):
        state = self.page.evaluate("""() => ({
            needed: slideTextContentHeight(document.getElementById('stretched')),
            row: 180
        })""")
        self.assertLess(state['needed'], 60)
        self.assertLess(state['needed'], state['row'])

    def _fit(self):
        return """() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const following = document.getElementById('following');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const raw = rawDoc.getElementById('target');
            const textRect = el => {
                const range = document.createRange();
                range.selectNodeContents(el);
                return range.getBoundingClientRect();
            };
            const rel = el => Math.round(el.getBoundingClientRect().top - slide.getBoundingClientRect().top);
            const beforeCenter = slideTextVisualCenterY(stage, target);
            const beforeFollowing = rel(following);
            const result = fitSlideTextPair(stage, target, raw, rawDoc.querySelector('.slide'), null);
            const box = target.getBoundingClientRect();
            const text = textRect(target);
            return {
                result,
                natural: slideTextContentHeight(target),
                boxHeight: target.offsetHeight,
                rawHeight: parseFloat(raw.style.height) || 0,
                centered: Math.abs((slideTextVisualCenterY(stage, target) || 0) - (beforeCenter || 0)) < 1.5,
                inside: text.top >= box.top - 1 && text.bottom <= box.bottom + 1,
                followingMoved: Math.abs(rel(following) - beforeFollowing),
                absolute: getComputedStyle(target).position,
                placeholders: slide.querySelectorAll('[data-slide-flow-placeholder]').length
            };
        }"""

    def test_fit_grows_a_box_that_is_shorter_than_its_text(self):
        state = self.page.evaluate(self._fit())
        self.assertTrue(state['result'])
        self.assertGreater(state['boxHeight'], 57)
        self.assertLessEqual(abs(state['boxHeight'] - state['natural']), 2)
        self.assertEqual(state['absolute'], 'absolute')
        self.assertEqual(state['placeholders'], 1)
        self.assertTrue(state['centered'])
        self.assertTrue(state['inside'])
        self.assertLessEqual(state['followingMoved'], 1)

    def test_fit_shrinks_a_box_that_is_taller_than_its_text(self):
        self.page.evaluate("""() => {
            const target = document.getElementById('target');
            target.style.height = '260px';
            target.style.minHeight = '0px';
        }""")
        state = self.page.evaluate(self._fit())
        self.assertTrue(state['result'])
        self.assertLess(state['boxHeight'], 260)
        self.assertLessEqual(abs(state['boxHeight'] - state['natural']), 2)
        self.assertTrue(state['centered'])
        self.assertTrue(state['inside'])
        self.assertLessEqual(state['followingMoved'], 1)
        self.assertLessEqual(abs(state['rawHeight'] - state['natural']), 2)

    def test_a_centred_box_shrinks_around_its_text_without_moving_it(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('centeredBox');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const raw = rawDoc.getElementById('centeredBox');
            const centre = el => {
                const range = document.createRange();
                range.selectNodeContents(el);
                const rect = range.getBoundingClientRect();
                return (rect.top + rect.bottom) / 2;
            };
            const before = {centre: centre(target), top: target.getBoundingClientRect().top};
            const result = fitSlideTextPair(stage, target, raw, rawDoc.querySelector('.slide'), null);
            const box = target.getBoundingClientRect();
            const range = document.createRange();
            range.selectNodeContents(target);
            const text = range.getBoundingClientRect();
            return {
                result,
                before: Math.round(before.top),
                height: target.offsetHeight,
                natural: slideTextContentHeight(target),
                centreShift: Math.abs(centre(target) - before.centre),
                inside: text.top >= box.top - 1 && text.bottom <= box.bottom + 1
            };
        }""")
        self.assertTrue(state['result'])
        self.assertLess(state['height'], 60)
        self.assertLessEqual(abs(state['height'] - state['natural']), 2)
        self.assertLess(state['centreShift'], 1.5)
        self.assertTrue(state['inside'])

    def test_a_width_change_rewraps_and_the_box_takes_the_new_height(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const raw = rawDoc.getElementById('target');
            const rawRoot = rawDoc.querySelector('.slide');
            fitSlideTextPair(stage, target, raw, rawRoot, null);
            const heightAt390 = target.offsetHeight;
            target.style.width = '190px';
            raw.style.width = '190px';
            const naturalAfter = slideTextContentHeight(target);
            fitSlideTextPair(stage, target, raw, rawRoot, null);
            const box = target.getBoundingClientRect();
            const range = document.createRange();
            range.selectNodeContents(target);
            const text = range.getBoundingClientRect();
            return {
                heightAt390,
                naturalAfter,
                height: target.offsetHeight,
                rawHeight: parseFloat(raw.style.height) || 0,
                inside: text.top >= box.top - 1 && text.bottom <= box.bottom + 1
            };
        }""")
        self.assertGreater(state['naturalAfter'], state['heightAt390'])
        self.assertLessEqual(abs(state['height'] - state['naturalAfter']), 2)
        self.assertLessEqual(abs(state['rawHeight'] - state['naturalAfter']), 2)
        self.assertTrue(state['inside'])

    def test_a_box_that_already_matches_its_text_is_left_in_the_flow(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            target.style.height = 'auto';
            target.style.minHeight = '0px';
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const raw = rawDoc.getElementById('target');
            const result = fitSlideTextPair(stage, target, raw, rawDoc.querySelector('.slide'), null);
            return {
                result,
                position: getComputedStyle(target).position,
                placeholders: slide.querySelectorAll('[data-slide-flow-placeholder]').length
            };
        }""")
        self.assertFalse(state['result'])
        self.assertEqual(state['position'], 'static')
        self.assertEqual(state['placeholders'], 0)

    def test_deleting_a_detached_box_releases_its_slot(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const rawRoot = rawDoc.querySelector('.slide');
            const raw = rawDoc.getElementById('target');
            fitSlideTextPair(stage, target, raw, rawRoot, null);
            const owner = target.getAttribute('data-slide-flow-owner');
            const placeholderOwner = slide.querySelector('[data-slide-flow-placeholder]').getAttribute('data-slide-flow-owner');
            removeSlideFlowPlaceholders(rawRoot, raw);
            raw.parentElement.removeChild(raw);
            return {
                owner: owner,
                placeholderOwner: placeholderOwner,
                sameOwner: !!owner && owner === placeholderOwner,
                placeholders: rawRoot.querySelectorAll('[data-slide-flow-placeholder]').length,
                owners: rawRoot.querySelectorAll('[data-slide-flow-owner]').length,
                targets: rawRoot.querySelectorAll('#target').length
            };
        }""")
        self.assertTrue(state['sameOwner'])
        self.assertEqual(state['placeholders'], 0)
        self.assertEqual(state['owners'], 0)
        self.assertEqual(state['targets'], 0)

    def test_a_legacy_placeholder_without_an_owner_is_released_by_geometry(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const rawRoot = rawDoc.querySelector('.slide');
            const raw = rawDoc.getElementById('target');
            fitSlideTextPair(stage, target, raw, rawRoot, null);
            // Decks saved before owners existed carry a bare placeholder.
            target.removeAttribute('data-slide-flow-owner');
            raw.removeAttribute('data-slide-flow-owner');
            slide.querySelectorAll('[data-slide-flow-owner]').forEach(el => el.removeAttribute('data-slide-flow-owner'));
            rawRoot.querySelectorAll('[data-slide-flow-owner]').forEach(el => el.removeAttribute('data-slide-flow-owner'));
            releaseSlideFlowSlot(stage, target, rawRoot, raw);
            raw.parentElement.removeChild(raw);
            return {
                placeholders: rawRoot.querySelectorAll('[data-slide-flow-placeholder]').length
            };
        }""")
        self.assertEqual(state['placeholders'], 0)

    def test_pasted_copies_do_not_own_the_original_slot(self):
        state = self.page.evaluate("""() => {
            const stage = document.querySelector('.tenant-slide-stage');
            const slide = stage.querySelector('.slide');
            const target = document.getElementById('target');
            const rawDoc = new DOMParser().parseFromString(slide.outerHTML, 'text/html');
            const raw = rawDoc.getElementById('target');
            fitSlideTextPair(stage, target, raw, rawDoc.querySelector('.slide'), null);
            const clone = raw.cloneNode(true);
            stripSlideFlowOwners(clone);
            return {
                original: raw.hasAttribute('data-slide-flow-owner'),
                clone: clone.hasAttribute('data-slide-flow-owner')
            };
        }""")
        self.assertTrue(state['original'])
        self.assertFalse(state['clone'])

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
