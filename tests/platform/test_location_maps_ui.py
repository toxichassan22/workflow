import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application_module
import db


class TestLocationMapsUI(unittest.TestCase):
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

    def test_location_css_in_bundle_order(self):
        """Verify project-form/01a_location_maps.css is registered in FRONTEND_CSS_ORDER."""
        css_order = getattr(application_module, 'FRONTEND_CSS_ORDER', ())
        self.assertIn(
            'project-form/01a_location_maps.css',
            css_order,
            "project-form/01a_location_maps.css must be registered in FRONTEND_CSS_ORDER."
        )

    def test_original_location_section_order_and_structure(self):
        """Verify Section 2 retains its exact original DOM order and natural flow without card wrappers."""
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        # Verify no card layout wrappers for location
        self.assertNotIn('location-card-identity', js_source)
        self.assertNotIn('location-card-maps', js_source)
        self.assertNotIn('location-card-tables', js_source)
        self.assertNotIn('location-form-section-v2', js_source)
        self.assertNotIn('locationOrderMap', js_source)

        # Verify button text is exact original 'تحليل رابط الموقع'
        self.assertIn("btn.textContent = 'تحليل رابط الموقع';", js_source)

        # Verify location tables are appended directly to sectionDiv
        self.assertIn("sectionDiv.appendChild(createLocationTableField(f.fieldKey", js_source)

        # Verify map preview is appended directly to locationSection or form at the end
        self.assertIn("(locationSection || form).appendChild(previewDiv);", js_source)

    def test_brand_palette_and_no_legacy_p_in_location_css(self):
        """Ensure Landloom brand colors (Navy #07182C, Teal #17C8E3 / #0FA9C4) and ZERO var(--p)."""
        css = self._read_file('assets/css/project-form/01a_location_maps.css')
        self.assertIn('#07182C', css)
        self.assertIn('#17C8E3', css)
        self.assertNotIn('var(--p)', css, "var(--p) must not exist in 01a_location_maps.css")

    def test_no_emojis_or_icon_glyphs(self):
        """Zero emojis or forbidden unicode icon glyphs."""
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u26ff]|[\u2700-\u27bf]'
        )
        css = self._read_file('assets/css/project-form/01a_location_maps.css')
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')
        self.assertEqual(emoji_pattern.findall(css), [], "Emoji found in 01a_location_maps.css")
        self.assertEqual(emoji_pattern.findall(js_source), [], "Emoji found in 02_catchment_edits.js")

    def test_no_how_to_instructions(self):
        """Screen must state what things are, never how to operate them."""
        css = self._read_file('assets/css/project-form/01a_location_maps.css')
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        forbidden_phrases = ['اضغط هنا', 'اختر أولاً', 'قم باختيار', 'يرجى الضغط']
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, css)
            self.assertNotIn(phrase, js_source)


if __name__ == '__main__':
    unittest.main()
