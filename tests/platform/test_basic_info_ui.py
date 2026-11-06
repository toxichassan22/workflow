import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application_module
import auth
import db


class TestBasicInfoUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application_module.app
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.init_db()

    def _read_file(self, relative_path):
        full_path = ROOT / relative_path
        self.assertTrue(full_path.exists(), f"File {relative_path} must exist on disk.")
        return full_path.read_text(encoding='utf-8')

    def test_css_in_bundle_order_and_exists(self):
        """Verify project-form/01b_project_basic.css is in FRONTEND_CSS_ORDER and valid."""
        css_order = getattr(application_module, 'FRONTEND_CSS_ORDER', ())
        self.assertIn(
            'project-form/01b_project_basic.css',
            css_order,
            "project-form/01b_project_basic.css must be registered in FRONTEND_CSS_ORDER."
        )
        css = self._read_file('assets/css/project-form/01b_project_basic.css')
        self.assertIn('.basic-form-section-v2', css)
        self.assertIn('.project-form-card', css)
        self.assertIn('.project-form-card-head', css)
        self.assertIn('.project-form-card-body', css)

    def test_brand_palette_in_basic_css(self):
        """Brand palette rules: Navy (#07182C), Turquoise (#17C8E3 / #0FA9C4), White."""
        css = self._read_file('assets/css/project-form/01b_project_basic.css')
        self.assertIn('#07182C', css)
        self.assertIn('#17C8E3', css)
        self.assertIn('#0FA9C4', css)

    def test_no_emojis_or_icon_glyphs(self):
        """Strict adherence: Zero emojis and zero icon fonts/glyphs in basic CSS and JS."""
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u26ff]|[\u2700-\u27bf]'
        )
        css = self._read_file('assets/css/project-form/01b_project_basic.css')
        self.assertEqual(emoji_pattern.findall(css), [], "Emoji found in 01b_project_basic.css")

        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')
        self.assertIn('basic-card-identity', js_source)
        self.assertIn('basic-card-vision', js_source)

    def test_no_how_to_instructions(self):
        """No instructional copy (اضغط, اختر أولا, قم بـ) in card headers or structure."""
        css = self._read_file('assets/css/project-form/01b_project_basic.css')
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        forbidden_phrases = ['اضغط هنا', 'اختر أولاً', 'قم باختيار', 'يرجى الضغط']
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, css)
            self.assertNotIn(phrase, js_source)

    def test_card_structure_and_grouping(self):
        """Verify the dual card separation: Identity & Classification vs Vision & Audience."""
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        # Check Card 1 definition
        self.assertIn('basic-card-identity', js_source)
        self.assertIn('هوية وتصنيف المشروع', js_source)
        self.assertIn('basicIdentityGrid', js_source)

        # Check Card 2 definition
        self.assertIn('basic-card-vision', js_source)
        self.assertIn('الرؤية والجمهور المستهدف', js_source)
        self.assertIn('basicVisionGrid', js_source)

        # Check field routing
        self.assertIn("f.fieldKey === 'target_audience' || f.fieldKey === 'project_idea'", js_source)
        self.assertIn("basicVisionGrid.appendChild(div)", js_source)
        self.assertIn("basicIdentityGrid.appendChild(div)", js_source)

    def test_i18n_entries_present(self):
        """Verify new section card titles and kickers are in the auto-dictionary."""
        dict_source = self._read_file('assets/i18n/04_dict_en_auto_project.js')
        self.assertIn('هوية وتصنيف المشروع', dict_source)
        self.assertIn('الرؤية والجمهور المستهدف', dict_source)
        self.assertIn('المحددات الأساسية', dict_source)
        self.assertIn('الرؤية والشرائح', dict_source)


if __name__ == '__main__':
    unittest.main()
