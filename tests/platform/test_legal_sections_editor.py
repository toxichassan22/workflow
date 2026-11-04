import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PART = ROOT / 'index_parts' / '24_platform_settings.html'
LEGAL_JS = ROOT / 'assets' / 'js' / '18-landloom-ops' / '03_legal_content.js'
AR_DICT = ROOT / 'assets' / 'i18n' / '01_dict_ar.js'
EN_DICT = ROOT / 'assets' / 'i18n' / '02_dict_en.js'

NODE_HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const code = fs.readFileSync(process.env.LEGAL_JS_PATH, 'utf8');
const sandbox = { window: {}, console: console };
sandbox.window = sandbox;
sandbox.document = { addEventListener() {} };
sandbox.WFT = function (key, fallback, params) {
  var out = fallback === undefined ? key : fallback;
  Object.keys(params || {}).forEach(function (name) {
    out = out.replace('{' + name + '}', String(params[name]));
  });
  return out;
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const sample = [
  '<h1>شروط الاستخدام</h1>',
  '<h2>1. قبول الشروط</h2>',
  '<p>نص الفقرة الأولى.</p>',
  '<h2>2. الحسابات</h2>',
  '<ul>',
  '<li><strong>بيانات الحساب:</strong> اسم الشركة والبريد.</li>',
  '<li>نقطة عادية.</li>',
  '</ul>'
].join('\n');

const parsed = sandbox.legalDocSections(sample);
assert.strictEqual(parsed.title, 'شروط الاستخدام');
assert.strictEqual(parsed.sections.length, 2);
assert.strictEqual(parsed.sections[0].title, '1. قبول الشروط');
assert.strictEqual(parsed.sections[0].body, 'نص الفقرة الأولى.');
assert.strictEqual(parsed.sections[1].bullets.length, 2);
assert.strictEqual(parsed.sections[1].bullets[0], 'بيانات الحساب: اسم الشركة والبريد.');

const html = sandbox.legalDocumentHtml(parsed);
assert.ok(html.indexOf('<h1>شروط الاستخدام</h1>') !== -1, 'h1 survives');
assert.ok(html.indexOf('<h2>2. الحسابات</h2>') !== -1, 'h2 survives');
assert.ok(html.indexOf('<strong>بيانات الحساب:</strong>') !== -1, 'bullet lead stays bold');
assert.ok(html.indexOf('<ul>') !== -1 && html.indexOf('<li>') !== -1, 'list survives');

const again = sandbox.legalDocSections(html);
assert.deepStrictEqual(JSON.parse(JSON.stringify(again)), JSON.parse(JSON.stringify(parsed)));

const risky = {
  title: 'Terms',
  sections: [{ title: 'Heading', body: '<script>alert(1)</script>', bullets: ['a & b'] }]
};
const riskyHtml = sandbox.legalDocumentHtml(risky);
assert.ok(riskyHtml.indexOf('<script>') === -1, 'markup in values must not survive');
assert.ok(riskyHtml.indexOf('&lt;script&gt;') !== -1, 'it is escaped instead');
assert.ok(riskyHtml.indexOf('a &amp; b') !== -1, 'ampersands are escaped');

assert.strictEqual(
  sandbox.legalDocumentIsEmpty({ title: 'x', sections: [{ title: '', body: '', bullets: [''] }] }),
  true
);
assert.strictEqual(
  sandbox.legalDocumentIsEmpty({ title: '', sections: [{ title: 'h', body: '', bullets: [] }] }),
  false
);

console.log('OK');
'''


class LegalSectionsEditorTests(unittest.TestCase):
    def test_settings_screen_replaces_html_boxes_with_sections(self):
        source = SETTINGS_PART.read_text(encoding='utf-8')
        self.assertNotIn('id="adminLegalAr"', source)
        self.assertNotIn('id="adminLegalEn"', source)
        self.assertNotIn('(HTML)', source)
        self.assertIn('id="adminLegalSections"', source)
        self.assertIn('adminAddLegalSection()', source)
        self.assertIn('id="adminLegalSaveBtn"', source)

    def test_editor_script_no_longer_reads_html_textareas(self):
        source = LEGAL_JS.read_text(encoding='utf-8')
        self.assertNotIn("getElementById('adminLegalAr')", source)
        self.assertNotIn("getElementById('adminLegalEn')", source)
        self.assertIn('function legalDocSections(', source)
        self.assertIn('function legalDocumentHtml(', source)

    def test_section_editor_keys_exist_in_both_dictionaries(self):
        ar = AR_DICT.read_text(encoding='utf-8')
        en = EN_DICT.read_text(encoding='utf-8')
        for key in (
            'admin.legal_sections',
            'admin.legal_sections_hint',
            'admin.legal_section',
            'admin.legal_heading',
            'admin.legal_text',
            'admin.legal_bullets',
            'admin.legal_add_bullet',
            'admin.legal_add_section',
            'admin.legal_move_up',
            'admin.legal_move_down',
            'admin.legal_delete',
            'admin.legal_preview',
            'admin.legal_no_sections',
        ):
            self.assertIn('"%s"' % key, ar, key)
            self.assertIn('"%s"' % key, en, key)
        self.assertNotIn('"admin.legal_ar"', ar)
        self.assertNotIn('"admin.legal_en"', ar)

    def test_section_parse_and_build_round_trip(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is required to execute the section editor helpers')
        env = dict(os.environ, LEGAL_JS_PATH=str(LEGAL_JS))
        proc = subprocess.run(
            [node, '-e', NODE_HARNESS],
            capture_output=True, text=True, cwd=str(ROOT), env=env
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn('OK', proc.stdout)

    def test_editor_script_parses_as_javascript(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is required to syntax-check the editor script')
        proc = subprocess.run(
            [node, '--check', str(LEGAL_JS)],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == '__main__':
    unittest.main()
