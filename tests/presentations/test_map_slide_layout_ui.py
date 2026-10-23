"""Map pages must read as designed slides, not as raw injected blocks.

The old map template put a 16:9 map inside a 540px-tall card with
`object-fit:contain`, so the map floated in white bands, the table stopped
short, and the date lived at the slide edge. These cases build the three map
pages, render them in Chromium, and measure the real alignment.
"""

import base64
import io
import unittest

from PIL import Image


class MapSlideLayoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise unittest.SkipTest(f'playwright is not installed: {error}')
        import slide_engine
        cls.engine = slide_engine
        image = Image.new('RGB', (1280, 720), (226, 235, 244))
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        cls.map_uri = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        cls.branding = {
            'primary_color': '#1a3a6b', 'accent_color': '#c59a58',
            'background_color': '#ffffff', 'text_color': '#1e293b',
        }
        cls.project = {
            'project_name': 'مشروع الاختبار',
            'location_data_fetched_at': '2026-10-22T09:13:00',
            'main_roads': 'نور العليا\nطريق المدينة المنورة',
            'city_landmarks_data': [
                {'name': f'وجهة {index}', 'distance_km': round(4 + index * 2.1, 1),
                 'duration_minutes': 8 + index * 3, 'category': 'خدمي'}
                for index in range(1, 8)
            ],
            'nearby_landmarks_data': [
                {'name': f'معلم {index}', 'category': 'خدمي',
                 'distance_km': round(1 + index * 0.7, 1), 'duration_minutes': 6 + index}
                for index in range(1, 9)
            ],
        }
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch()
        cls.page = cls.browser.new_page(viewport={'width': 1280, 'height': 720})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()

    def _render(self, slide_type, title, token):
        raw = self.engine._build_structured_fallback_slide(
            {'title': title, 'type': slide_type}, self.project, self.branding, 16, 80)
        html = self.engine.finalize_slide_html(
            raw, slide_type, self.project, self.branding, slide_num=16,
            slide_title=title, total_slides=80, map_placeholders={token: self.map_uri})
        self.page.set_content(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<style>body{margin:0}</style></head><body>' + html + '</body></html>')
        return self.page.evaluate(
            """() => {
                   const slide = document.querySelector('.slide');
                   const cap = slide.querySelector('[data-map-caption]');
                   const mapCard = cap.parentElement.parentElement;
                   const image = mapCard.querySelector('img');
                   const imageWrap = image.parentElement;
                   const table = slide.querySelector('table');
                   const tableCard = table.closest('div[style*="border-radius:14px"]');
                   const leftColumn = tableCard.parentElement;
                   const rows = Array.from(table.querySelectorAll('tbody tr'));
                   const header = slide.querySelector('[data-slide-header]');
                   const footer = slide.querySelector('[data-slide-footer]');
                   let contentBottom = 0;
                   slide.querySelectorAll('*').forEach(element => {
                       if (element.closest('[data-slide-header],[data-slide-footer]')) return;
                       const rect = element.getBoundingClientRect();
                       if (rect.height > 1) contentBottom = Math.max(contentBottom, rect.bottom);
                   });
                   const R = element => element.getBoundingClientRect();
                   return {
                       mapCardTop: Math.round(R(mapCard).top),
                       mapCardBottom: Math.round(R(mapCard).bottom),
                       imageTop: Math.round(R(image).top),
                       imageBottom: Math.round(R(image).bottom),
                       imageWrapTop: Math.round(R(imageWrap).top),
                       imageWrapBottom: Math.round(R(imageWrap).bottom),
                       tableCardTop: Math.round(R(tableCard).top),
                       tableCardBottom: Math.round(R(tableCard).bottom),
                       leftColumnBottom: Math.round(R(leftColumn).bottom),
                       lastRowBottom: Math.round(R(rows[rows.length - 1]).bottom),
                       headerBottom: Math.round(R(header).bottom),
                       footerTop: Math.round(R(footer).top),
                       contentBottom: Math.round(contentBottom),
                       caption: cap.innerText,
                       tableRows: rows.length,
                   };
               }""")

    def _assert_designed_map(self, metrics):
        self.assertEqual(metrics['tableRows'] > 0, True, metrics)
        # Table and map start on the same line, and the column owns the map height.
        self.assertLessEqual(abs(metrics['tableCardTop'] - metrics['mapCardTop']), 2, metrics)
        self.assertLessEqual(abs(metrics['leftColumnBottom'] - metrics['mapCardBottom']), 4, metrics)
        # A 16:9 map fills its wrapper: no white bands above or below it.
        self.assertLessEqual(abs(metrics['imageTop'] - metrics['imageWrapTop']), 2, metrics)
        self.assertLessEqual(abs(metrics['imageBottom'] - metrics['imageWrapBottom']), 2, metrics)
        # The table's last row is inside the card, and everything clears the footer.
        self.assertLessEqual(metrics['lastRowBottom'], metrics['leftColumnBottom'] + 1, metrics)
        self.assertLessEqual(metrics['contentBottom'], metrics['footerTop'] - 8, metrics)
        self.assertGreaterEqual(metrics['mapCardTop'], metrics['headerBottom'] + 6, metrics)
        self.assertIn('تم قياس زمن القيادة', metrics['caption'])

    def test_access_map_is_a_designed_aligned_page(self):
        metrics = self._render('map_access', 'خريطة الطرق الرئيسية', '##MAP_ACCESS##')
        self._assert_designed_map(metrics)
        self.assertEqual(metrics['tableRows'], 2)

    def test_catchment_map_is_a_designed_aligned_page(self):
        metrics = self._render('map_catchment', 'خريطة المنطقة ونطاق التأثير', '##MAP_CATCHMENT##')
        self._assert_designed_map(metrics)
        self.assertEqual(metrics['tableRows'], 7)

    def test_landmarks_map_is_a_designed_aligned_page(self):
        metrics = self._render('map_landmarks', 'خريطة المعالم القريبة', '##MAP_LANDMARKS##')
        self._assert_designed_map(metrics)
        # The table renders the same selected set as the map (up to seven).
        self.assertEqual(metrics['tableRows'], 7)


if __name__ == '__main__':
    unittest.main()
