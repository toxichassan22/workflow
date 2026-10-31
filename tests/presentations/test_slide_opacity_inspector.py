"""The opacity control must reach the value the client types.

A logo often sits inside a wrapper that carries the fade (the cover logo card
is one). A child can never be more visible than its ancestor, so the old
effective-opacity maths clamped every request to the wrapper's value: the field
snapped back to 5% and the element could never be brightened again. These cases
run the real browser functions against such a wrapper.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITING = ROOT / 'assets' / 'js' / '14-slides-gen' / '02_element_editing.js'
PROGRESS = ROOT / 'assets' / 'js' / '13-visual' / '02_slides_progress.js'


def _slice(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class SlideOpacityInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        editing = EDITING.read_text(encoding='utf-8')
        progress = PROGRESS.read_text(encoding='utf-8')
        opacity = _slice(editing, 'function slideElementOpacityProduct(',
                         'function previewSlideElementOpacity(')
        # The path helpers and elementAtSlidePath close the file.
        paths = progress[progress.index('function slidePathIgnores('):]
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page()
        cls.page.set_content('<!doctype html><html><body></body></html>')
        cls.page.add_script_tag(content=paths + '\n' + opacity)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def test_a_faded_wrapper_is_lifted_to_reach_the_requested_opacity(self):
        result = self.page.evaluate(
            """() => {
                   document.body.innerHTML =
                       '<div class="slide"><div id="card" style="opacity:0.05">'
                       + '<img id="logo" src="x.png" style="opacity:1"></div></div>';
                   const logo = document.getElementById('logo');
                   const actual = applySlideElementEffectiveOpacity(logo, 60);
                   return {
                       actual,
                       card: document.getElementById('card').style.opacity,
                       logo: logo.style.opacity,
                       readout: slideElementOpacityPct(logo),
                   };
               }"""
        )
        self.assertEqual(result['actual'], 60)
        self.assertAlmostEqual(float(result['card']), 0.6, places=3)
        self.assertAlmostEqual(float(result['logo']), 1.0, places=3)
        self.assertEqual(result['readout'], 60)

    def test_a_plain_element_keeps_its_own_opacity(self):
        result = self.page.evaluate(
            """() => {
                   document.body.innerHTML =
                       '<div class="slide"><img id="logo" src="x.png"></div>';
                   const logo = document.getElementById('logo');
                   const actual = applySlideElementEffectiveOpacity(logo, 40);
                   return { actual, logo: logo.style.opacity, readout: slideElementOpacityPct(logo) };
               }"""
        )
        self.assertEqual(result['actual'], 40)
        self.assertAlmostEqual(float(result['logo']), 0.4, places=3)
        self.assertEqual(result['readout'], 40)

    def test_a_lowered_wrapper_is_mirrored_into_the_stored_copy(self):
        result = self.page.evaluate(
            """() => {
                   document.body.innerHTML =
                       '<div class="slide"><div id="card" style="opacity:0.05">'
                       + '<img id="logo" src="x.png"></div></div>';
                   const liveSlide = document.querySelector('.slide');
                   const logo = document.getElementById('logo');
                   applySlideElementEffectiveOpacity(logo, 60);
                   const rawDoc = new DOMParser().parseFromString(
                       '<div class="slide"><div style="opacity:0.05"><img src="x.png"></div></div>',
                       'text/html');
                   const rawRoot = rawDoc.querySelector('.slide');
                   mirrorSlideAncestorOpacity(liveSlide, rawRoot, logo);
                   return { raw: rawRoot.querySelector('div').style.opacity };
               }"""
        )
        self.assertAlmostEqual(float(result['raw']), 0.6, places=3)

    def test_the_commit_path_mirrors_the_ancestor_chain(self):
        source = EDITING.read_text(encoding='utf-8')
        commit = _slice(source, 'function commitSlideElementOpacity(',
                        'function slideElementFontSizePx(')
        self.assertIn('mirrorSlideAncestorOpacity(slide, rawRoot, liveLayer);', commit)


if __name__ == '__main__':
    unittest.main()
