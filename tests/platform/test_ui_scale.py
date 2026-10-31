"""The product renders at one fixed scale (`.85`), not at the browser's 100%.

The owner reads the whole app at 75–85% browser zoom, so the shell itself is
built at that size: `--ui-scale` drives a root `zoom`, and every full-height
container measures the viewport through `--ui-viewport` / `--ui-width` instead
of a bare `100vh` — a raw `100vh` under a zoomed root stops 15% short and leaves
a strip at the bottom of the screen.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'assets' / 'css' / 'base'
FORMS = ROOT / 'assets' / 'css' / 'project-form'


def _bundle_css():
    part = ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py'
    tree = ast.parse(part.read_text(encoding='utf-8'))
    names = ()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == 'FRONTEND_CSS_ORDER' for t in node.targets):
            continue
        names = tuple(ast.literal_eval(node.value))
    return '\n'.join((ROOT / 'assets' / 'css' / name).read_text(encoding='utf-8') for name in names)


class UiScaleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell_css = (BASE / '04_export_responsive.css').read_text(encoding='utf-8')
        cls.bundle_css = _bundle_css()

    def test_root_declares_one_fixed_scale_and_applies_it(self):
        match = re.search(r'--ui-scale:\s*([0-9.]+);', self.shell_css)
        self.assertIsNotNone(match, '--ui-scale missing from :root')
        scale = float(match.group(1))
        # A fixed product size: readable, but visibly denser than 100%.
        self.assertGreaterEqual(scale, 0.75)
        self.assertLessEqual(scale, 0.95)
        self.assertIn('--ui-viewport: calc(100vh / var(--ui-scale));', self.shell_css)
        self.assertIn('--ui-width: calc(100vw / var(--ui-scale));', self.shell_css)
        html_rule = self.shell_css.split('html {', 1)[1].split('}', 1)[0]
        self.assertIn('zoom: var(--ui-scale);', html_rule)

    def test_full_height_shells_use_the_scaled_viewport(self):
        # A bare 100vh inside the zoomed root renders 15% short.
        app = self.shell_css.split('.tenant-app {', 1)[1].split('}', 1)[0]
        self.assertIn('min-height: var(--ui-viewport);', app)
        self.assertIn('minmax(calc(var(--ui-viewport) - 68px), auto)', app)
        sidebar = self.shell_css.split('width: 264px;', 1)[1].split('}', 1)[0]
        self.assertIn('height: var(--ui-viewport);', sidebar)
        page = self.shell_css.split('max-width: 1600px;', 1)[1].split('}', 1)[0]
        self.assertIn('min-height: calc(var(--ui-viewport) - 68px);', page)

        preview = (BASE / '01_preview_chat.css').read_text(encoding='utf-8')
        deck_page = preview.split('.tenant-app.preview-active>#tenantSlidesPage {', 1)[1]
        deck_page = deck_page.split('}', 1)[0]
        self.assertIn('height: var(--ui-viewport) !important;', deck_page)
        self.assertIn('height: calc(var(--ui-viewport) - 65px) !important;',
                      preview.split('.tenant-app.preview-active .ge-body {', 1)[1].split('}', 1)[0])

    def test_no_bare_viewport_unit_survives_in_the_bundle(self):
        for match in re.finditer(r'(?<![\w-])(\d+)vh\b', self.bundle_css):
            line_start = self.bundle_css.rfind('\n', 0, match.start()) + 1
            line = self.bundle_css[line_start:self.bundle_css.find('\n', match.start())]
            # Allowed: the scale definitions themselves and the var() fallbacks
            # that keep a stylesheet usable on its own.
            self.assertTrue(
                '--ui-viewport' in line or 'var(--ui-viewport' in line or line.strip().startswith('*'),
                'bare viewport unit left in: ' + line.strip(),
            )
        # Width fractions inside a clamp() are gutters, not the screen edge; a
        # bare 100vw is what leaves a margin on the side.
        for match in re.finditer(r'(?<![\w-])(100)vw\b', self.bundle_css):
            line_start = self.bundle_css.rfind('\n', 0, match.start()) + 1
            line = self.bundle_css[line_start:self.bundle_css.find('\n', match.start())]
            self.assertTrue(
                '--ui-width' in line or 'var(--ui-width' in line,
                'bare viewport unit left in: ' + line.strip(),
            )


if __name__ == '__main__':
    unittest.main()
