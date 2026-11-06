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
        css = self._read_file('assets/css/project-form/01a_location_maps.css')
        self.assertIn('.location-form-section-v2', css)
        self.assertIn('.location-card-identity', css)
        self.assertIn('#locationIdentityGrid', css)

    def test_three_card_structure_and_routing(self):
        """Verify Section 2 split into 3 cards: Identity & Coordinates, Interactive Maps, and Tables."""
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        # Card 1: Geographic Site & Coordinates
        self.assertIn('location-card-identity', js_source)
        self.assertIn('الموقع الجغرافي وبيانات الأرض', js_source)
        self.assertIn('locationIdentityGrid', js_source)

        # Card 2: Interactive Maps & 4 Generated Views
        self.assertIn('location-card-maps', js_source)
        self.assertIn('معاينة الخرائط المولدة والتحكم البصري', js_source)
        self.assertIn('locationMapsBody', js_source)

        # Card 3: Roads Network & Landmarks Tables
        self.assertIn('location-card-tables', js_source)
        self.assertIn('شبكة الطرق والمحاور والمعالم الحيوية', js_source)
        self.assertIn('locationTablesBody', js_source)

        # Verify field routing
        self.assertIn("locationIdentityGrid.appendChild(div)", js_source)
        self.assertIn("(locationTablesCard || sectionDiv).appendChild(createLocationTableField", js_source)
        self.assertIn("(locationMapsCard || locationSection || form).appendChild(previewDiv)", js_source)

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
        self.assertEqual(emoji_pattern.findall(css), [], "Emoji found in 01a_location_maps.css")

    def test_no_how_to_instructions(self):
        """Screen must state what things are, never how to operate them."""
        css = self._read_file('assets/css/project-form/01a_location_maps.css')
        js_source = self._read_file('assets/js/08-location-maps/02_catchment_edits.js')

        forbidden_phrases = ['اضغط هنا', 'اختر أولاً', 'قم باختيار', 'يرجى الضغط']
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, css)
            self.assertNotIn(phrase, js_source)

    def test_i18n_entries_present(self):
        """Verify new Section 2 card titles and kickers are registered in the dictionary."""
        dict_source = self._read_file('assets/i18n/04_dict_en_auto_project.js')
        self.assertIn('المحددات المكانية', dict_source)
        self.assertIn('الموقع الجغرافي وبيانات الأرض', dict_source)
        self.assertIn('التحليل المكاني والخرائط', dict_source)
        self.assertIn('معاينة الخرائط المولدة والتحكم البصري', dict_source)
        self.assertIn('الوصولية والمعالم', dict_source)
        self.assertIn('شبكة الطرق والمحاور والمعالم الحيوية', dict_source)


if __name__ == '__main__':
    unittest.main()
