"""UI internationalization (i18n) foundation guards.

The shell (index.html) carries thousands of legacy hardcoded Arabic UI strings.
Translating all of them at once is not feasible, so this suite does two things:

1. It locks the CURRENT state behind a ratchet: the legacy literals are listed
   in ``i18n_hardcoded_baseline.txt`` and ``test_no_new_hardcoded_ui_strings``
   fails when a NEW hardcoded Arabic UI literal appears in toast() /
   confirm() / placeholder="" / showLoader() / hideLoader() /
   updateLoaderProgress(). Migrate the old literal to WFT()/data-i18n instead;
   the baseline only ever shrinks.
2. It keeps the ``assets/i18n.js`` dictionaries honest: identical key sets in
   both languages, no empty values, real English on the en side, and the shell
   actually loading the file before its application scripts.

To regenerate the baseline AFTER deliberately migrating literals (never to
silence this test for new strings)::

    python tests/test_i18n.py --rebuild-baseline

Run as a module from the repo root like every other suite::

    python -m unittest tests.test_i18n
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'index.html'
I18N_JS = ROOT / 'assets' / 'i18n.js'
I18N_DICT_DIR = ROOT / 'assets' / 'i18n'
BASELINE = Path(__file__).resolve().parent / 'i18n_hardcoded_baseline.txt'

# index.html is a slim shell: styles live in assets/css and code in these
# classic scripts, loaded in order so they keep one shared global scope.
FRONTEND_CSS_ORDER = (
    'base/01_preview_chat.css', 'base/02_tenant_pages.css',
    'base/03_the_view_model.css', 'base/04_export_responsive.css',
    'base/05_dashboard_viz.css',
    'project-form/01_sections_changelog.css',
    'project-form/02_fields_tables_rail.css',
)
FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '06-team.js', '07-project-form/01_form_sections.js',
    '07-project-form/02_section_versions.js', '08-location-maps/01_tables_approvals.js',
    '08-location-maps/02_catchment_edits.js', '09-financial/01_financial_format.js',
    '09-financial/02_formulas_calc.js',
    '10-financial-report-timeline/01_report_collect.js',
    '10-financial-report-timeline/02_timeline_sidebar.js', '11-land-croquis/01_croquis_survey.js',
    '11-land-croquis/02_map_edits.js', '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js', '14-slides-gen/01_undo.js',
    '14-slides-gen/02_element_editing.js', '15-slide-edit-chat/01_render_inline_edit.js',
    '15-slide-edit-chat/02_designer_chat.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js', '17-admin-boot/01_training_rules.js',
    '17-admin-boot/02_users_roles.js', '18-landloom-ops.js',
    '19-notifications.js',
)


def read_module_source(name):
    """Full source of a backend module: the slim <name> file plus every ordered
    part under <stem>_parts/ concatenated in exec order."""
    text = (ROOT / name).read_text(encoding='utf-8')
    parts_dir = ROOT / (name[:-3] + '_parts')
    if parts_dir.is_dir():
        for part in sorted(parts_dir.glob('*.py')):
            text += part.read_text(encoding='utf-8')
    return text


def read_shell():
    return INDEX.read_text(encoding='utf-8')


def read_frontend_text():
    """Shell + styles + scripts in load order: the whole client source."""
    parts = [read_shell()]
    for name in FRONTEND_CSS_ORDER:
        parts.append((ROOT / 'assets' / 'css' / name).read_text(encoding='utf-8'))
    for name in FRONTEND_JS_ORDER:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)

AR_CHAR = r'[\u0600-\u06FF]'

# (kind, compiled pattern). Every pattern captures the literal in group 2,
# except 'placeholder' which captures the attribute value in group 1.
CALL_PATTERNS = (
    ('toast', re.compile(r"toast\(\s*([`'\"])(.*?)\1", re.S)),
    ('confirm', re.compile(r"confirm\(\s*([`'\"])(.*?)\1", re.S)),
    ('loader', re.compile(
        r"(?:showLoader|hideLoader|updateLoaderProgress)\(\s*([`'\"])(.*?)\1",
        re.S)),
)

PLACEHOLDER_TAG_RE = re.compile(r'<[^>]*>', re.S)
PLACEHOLDER_ATTR_RE = re.compile(r'placeholder\s*=\s*"([^"]*)"')

KEY_RE = re.compile(r'^[a-z0-9_.]+$')


def _strip_inert(html):
    """Drop HTML and JS block comments so examples in comments are not flagged."""
    html = re.sub(r'<!--[\s\S]*?-->', '', html)
    return re.sub(r'/\*[\s\S]*?\*/', '', html)


def _normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def extract_hardcoded_ui_strings(html):
    """Return the sorted unique ``kind|text`` violations in the shell.

    Deliberately narrow: only the call sites where new hardcoded UI chrome
    sneaks in (toasts, confirms, placeholders, loader steps). Literals inside
    WFT('key', 'fallback') never match because the quote does not directly
    follow the call paren, and placeholders on tags already carrying
    data-i18n-ph are the migrated form, so they are skipped.
    """
    found = set()
    code = _strip_inert(html)
    for kind, pattern in CALL_PATTERNS:
        for match in pattern.finditer(code):
            line_start = code.rfind('\n', 0, match.start()) + 1
            stripped = code[line_start:match.start()].strip()
            if stripped.startswith('//') or stripped.startswith('*'):
                continue
            text = _normalize(match.group(2))
            if text and re.search(AR_CHAR, text):
                found.add('%s|%s' % (kind, text))
    for tag in PLACEHOLDER_TAG_RE.finditer(code):
        tag_text = tag.group(0)
        if 'data-i18n-ph' in tag_text:
            continue
        for attr in PLACEHOLDER_ATTR_RE.finditer(tag_text):
            text = _normalize(attr.group(1))
            if text and re.search(AR_CHAR, text):
                found.add('placeholder|%s' % text)
    return sorted(found)


def read_dict_source():
    """The dictionary part files concatenated: assets/i18n/*.js in order."""
    return '\n'.join(
        p.read_text(encoding='utf-8')
        for p in sorted(I18N_DICT_DIR.glob('*.js')))


def read_dicts():
    """Parse the JSON-compatible dict blocks out of assets/i18n/*.js."""
    src = read_dict_source()
    dicts = {}
    for lang in ('AR', 'EN'):
        match = re.search(
            r'/\*I18N_%s_BEGIN\*/(.*?)/\*I18N_%s_END\*/' % (lang, lang),
            src, re.S)
        if not match:
            raise AssertionError(
                'assets/i18n.js lost its I18N_%s markers' % lang)
        dicts[lang.lower()] = json.loads(match.group(1))
    return dicts


def load_baseline():
    if not BASELINE.exists():
        return None
    return sorted(
        line.strip() for line in
        BASELINE.read_text(encoding='utf-8').splitlines() if line.strip())


class I18nFoundationTests(unittest.TestCase):
    def test_i18n_file_exists_and_shell_loads_it_first(self):
        self.assertTrue(I18N_JS.exists(), 'assets/i18n.js is missing')
        html = read_shell()
        tag = html.find('/assets/i18n.js')
        self.assertNotEqual(
            tag, -1,
            'index.html must include <script src="/assets/i18n.js">')
        # Absolute path: client routes (/app/..., /c/<slug>) would resolve a
        # relative assets/... URL against the deep link and 404.
        self.assertIn('src="/assets/i18n.js"', html)
        # The dictionaries ship as assets/i18n/*.js and must load before the
        # runtime that reads window.__WFI18N_*.
        dict_files = sorted(p.name for p in I18N_DICT_DIR.glob('*.js'))
        self.assertTrue(dict_files, 'assets/i18n/ dictionary files are missing')
        prev = -1
        for name in dict_files:
            pos = html.find('src="/assets/i18n/%s"' % name)
            self.assertNotEqual(
                pos, -1, 'index.html must load /assets/i18n/%s' % name)
            self.assertLess(
                pos, tag, 'assets/i18n/%s must load before i18n.js' % name)
            self.assertGreater(pos, prev, 'dictionary order must match the sorted names')
            prev = pos
        # The old single inline <script> block is gone: code ships as ordered
        # classic scripts sharing one global scope (no async, no modules).
        bare_scripts = [
            m.start() for m in
            re.finditer(r'^\s*<script>\s*$', html, re.M)]
        self.assertEqual(
            bare_scripts, [],
            'index.html must not carry an inline <script> block anymore; '
            'put the code in assets/js/')
        # The shell references server-built bundles, never part files: twenty
        # part requests per refresh became two. The bundle order authority is
        # app.py (FRONTEND_*_ORDER) and must match this suite's pin exactly.
        self.assertIn(
            'href="/assets/app.bundle.css"', html,
            'index.html must link /assets/app.bundle.css')
        self.assertNotIn(
            '/assets/css/base.css', html,
            'index.html must not reference part CSS files directly')
        bundle_tags = re.findall(
            r'<script src="/assets/app\.bundle\.js"></script>', html)
        self.assertEqual(
            len(bundle_tags), 1,
            'index.html must load /assets/app.bundle.js exactly once')
        self.assertNotIn(
            '/assets/js/', html,
            'index.html must not reference part JS files directly')
        app_source = read_module_source('app.py')

        def _order(name):
            match = re.search(name + r'\s*=\s*\((.*?)\)', app_source, re.S)
            self.assertIsNotNone(match, 'app.py must define %s' % name)
            return tuple(re.findall(r"'([^']+)'", match.group(1)))

        self.assertEqual(
            _order('FRONTEND_JS_ORDER'), FRONTEND_JS_ORDER,
            'app.py bundle order drifted from the pinned FRONTEND_JS_ORDER')
        self.assertEqual(
            _order('FRONTEND_CSS_ORDER'), FRONTEND_CSS_ORDER,
            'app.py bundle order drifted from the pinned FRONTEND_CSS_ORDER')
        for name in FRONTEND_CSS_ORDER:
            self.assertTrue(
                (ROOT / 'assets' / 'css' / name).exists(),
                'assets/css/%s is missing' % name)
        for name in FRONTEND_JS_ORDER:
            self.assertTrue(
                (ROOT / 'assets' / 'js' / name).exists(),
                'assets/js/%s is missing' % name)
        first_app = html.find('/assets/app.bundle.js')
        self.assertLess(
            tag, first_app,
            'assets/i18n.js must load BEFORE the application bundle so '
            'WFI18n/WFT exist when application code runs')

    def test_runtime_api_is_present(self):
        src = I18N_JS.read_text(encoding='utf-8')
        for token in ('window.WFI18n', 'window.WFT', 'window.toggleAppLanguage',
                      'wf:lang', 'wf.lang', 'data-i18n',
                      'document.documentElement', 'WFI18N_EN_AUTO',
                      'autoTranslate', 'autoRestore', 'TreeWalker',
                      'MutationObserver', 'isConnected'):
            self.assertIn(token, src, 'assets/i18n.js must define %s' % token)
        # Generated-deck and AI-chat content must never be touched: the offer
        # language is a separate concern from the UI language.
        for guard in ('.ge-slide-card', '#tenantChatMessages',
                      '.tenant-chat-messages', 'textarea', 'option'):
            self.assertIn(
                guard, src,
                'auto-translate skip list must keep %s' % guard)
        html = INDEX.read_text(encoding='utf-8')
        self.assertIn('langToggleBtn', html)
        self.assertIn('toggleAppLanguage', html)

    def test_dicts_are_in_sync_and_real(self):
        dicts = read_dicts()
        ar_keys = set(dicts['ar'])
        en_keys = set(dicts['en'])
        self.assertTrue(ar_keys, 'Arabic dict is empty')
        self.assertEqual(
            ar_keys, en_keys,
            'dictionaries out of sync: ar-only=%s en-only=%s' % (
                sorted(ar_keys - en_keys), sorted(en_keys - ar_keys)))
        for key in ar_keys:
            self.assertTrue(
                KEY_RE.match(key), 'bad key (ascii snake_case, dots): %r' % key)
            self.assertTrue(
                str(dicts['ar'][key]).strip(), 'empty ar value: %s' % key)
            self.assertTrue(
                str(dicts['en'][key]).strip(), 'empty en value: %s' % key)
            if not key.startswith('lang.'):
                # lang.* legitimately names a language in its own script.
                self.assertNotRegex(
                    str(dicts['en'][key]), AR_CHAR,
                    'en value carries Arabic script: %s' % key)

    def test_static_bindings_reference_known_keys(self):
        dicts = read_dicts()
        html = read_shell()
        used = set(re.findall(r'data-i18n(?:-ph|-title|-aria)?="([^"]+)"', html))
        self.assertTrue(used, 'no data-i18n bindings found in index.html')
        unknown = sorted(k for k in used if k not in dicts['ar'])
        self.assertEqual(
            unknown, [],
            'data-i18n keys missing from assets/i18n.js: %s' % unknown)

    def test_no_new_hardcoded_ui_strings(self):
        baseline = load_baseline()
        self.assertIsNotNone(
            baseline,
            'baseline file missing: %s (regenerate with '
            'python tests/test_i18n.py --rebuild-baseline)' % BASELINE)
        current = extract_hardcoded_ui_strings(read_frontend_text())
        fresh = [v for v in current if v not in set(baseline)]
        self.assertEqual(
            fresh, [],
            'NEW hardcoded Arabic UI strings in index.html. Put the text in '
            'assets/i18n.js (both languages) and use WFT()/data-i18n instead:\n'
            + '\n'.join(fresh))

    def test_auto_map_is_real_and_safe(self):
        src = read_dict_source()
        match = re.search(
            r'/\*I18N_EN_AUTO_BEGIN\*/(.*?)/\*I18N_EN_AUTO_END\*/', src, re.S)
        self.assertIsNotNone(
            match, 'assets/i18n.js lost its I18N_EN_AUTO markers')
        auto = json.loads(match.group(1))
        self.assertGreaterEqual(
            len(auto), 1000,
            'EN_AUTO map shrank unexpectedly: %d entries' % len(auto))
        for key, value in auto.items():
            self.assertRegex(
                key, AR_CHAR, 'auto key without Arabic: %r' % key)
            self.assertNotIn('{', key, 'unrenderable fragment key: %r' % key)
            self.assertNotIn('}', key, 'unrenderable fragment key: %r' % key)
            self.assertTrue(
                isinstance(value, str) and value.strip(),
                'empty en_auto value: %s' % key)
            self.assertNotRegex(
                value, AR_CHAR, 'en_auto value carries Arabic: %s' % key)
        # Product terminology must stay consistent with the dotted dicts.
        for ar, en in (('مسودة', 'Draft'), ('معتمد', 'Approved'),
                       ('كروكي', 'Croquis'), ('الدراسة المالية', 'Financial study'),
                       ('تعميد العروض', 'Offer approval'),
                       ('سكني', 'Residential'),
                       ('الملخص التنفيذي', 'Executive summary')):
            self.assertEqual(
                auto.get(ar), en,
                'en_auto[%r] should stay %r' % (ar, en))

    def test_i18n_js_parses_as_javascript(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        targets = [I18N_JS] + sorted(I18N_DICT_DIR.glob('*.js')) + [
            ROOT / 'assets' / 'js' / name for name in FRONTEND_JS_ORDER]
        for target in targets:
            proc = subprocess.run(
                [node, '--check', str(target)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(
                proc.returncode, 0,
                'node --check %s failed:\n%s' % (target.name, proc.stderr))


def _rebuild_baseline():
    current = extract_hardcoded_ui_strings(read_frontend_text())
    BASELINE.write_text('\n'.join(current) + '\n', encoding='utf-8')
    print('baseline rewritten: %d entries -> %s' % (len(current), BASELINE))


if __name__ == '__main__':
    if '--rebuild-baseline' in sys.argv:
        _rebuild_baseline()
    else:
        unittest.main()
