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
   actually loading the file before its main inline script.

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
BASELINE = Path(__file__).resolve().parent / 'i18n_hardcoded_baseline.txt'

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


def read_dicts():
    """Parse the two JSON-compatible dict blocks out of assets/i18n.js."""
    src = I18N_JS.read_text(encoding='utf-8')
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
        html = INDEX.read_text(encoding='utf-8')
        tag = html.find('/assets/i18n.js')
        self.assertNotEqual(
            tag, -1,
            'index.html must include <script src="/assets/i18n.js">')
        # Absolute path: client routes (/app/..., /c/<slug>) would resolve a
        # relative assets/... URL against the deep link and 404.
        self.assertIn('src="/assets/i18n.js"', html)
        bare_scripts = [
            m.start() for m in
            re.finditer(r'^\s*<script>\s*$', html, re.M)]
        self.assertTrue(
            bare_scripts,
            'main inline <script> block not found in index.html')
        self.assertLess(
            tag, bare_scripts[-1],
            'assets/i18n.js must load BEFORE the main inline script so '
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
        html = INDEX.read_text(encoding='utf-8')
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
        current = extract_hardcoded_ui_strings(
            INDEX.read_text(encoding='utf-8'))
        fresh = [v for v in current if v not in set(baseline)]
        self.assertEqual(
            fresh, [],
            'NEW hardcoded Arabic UI strings in index.html. Put the text in '
            'assets/i18n.js (both languages) and use WFT()/data-i18n instead:\n'
            + '\n'.join(fresh))

    def test_auto_map_is_real_and_safe(self):
        src = I18N_JS.read_text(encoding='utf-8')
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
        proc = subprocess.run(
            [node, '--check', str(I18N_JS)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(
            proc.returncode, 0,
            'node --check assets/i18n.js failed:\n%s' % proc.stderr)


def _rebuild_baseline():
    current = extract_hardcoded_ui_strings(INDEX.read_text(encoding='utf-8'))
    BASELINE.write_text('\n'.join(current) + '\n', encoding='utf-8')
    print('baseline rewritten: %d entries -> %s' % (len(current), BASELINE))


if __name__ == '__main__':
    if '--rebuild-baseline' in sys.argv:
        _rebuild_baseline()
    else:
        unittest.main()
