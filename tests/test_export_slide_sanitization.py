import unittest
from pathlib import Path

from design_templates import extract_slide_elements

ROOT = Path(__file__).resolve().parents[1]


class ExportSlideSanitizationTests(unittest.TestCase):
    def test_discards_text_after_each_slide(self):
        html = (
            '<div class="slide"><div>one</div></div>!\n'
            '<div class="slide"><div>two</div></div>!'
        )

        slides = extract_slide_elements(html)

        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0], '<div class="slide"><div>one</div></div>')
        self.assertEqual(slides[1], '<div class="slide"><div>two</div></div>')

    def test_handles_slide_class_among_multiple_classes(self):
        html = '<p>AI chatter</p><div class="printable slide active"><div>x</div></div>done'

        self.assertEqual(
            extract_slide_elements(html),
            ['<div class="printable slide active"><div>x</div></div>'],
        )

    def test_repairs_an_unbalanced_slide_instead_of_dropping_it(self):
        """It used to return [] here, and that is what shipped a PDF that ended mid-deck."""
        self.assertEqual(
            extract_slide_elements('<div class="slide"><div>broken</div>'),
            ['<div class="slide"><div>broken</div></div>'],
        )

    def test_one_broken_slide_cannot_drop_the_slides_after_it(self):
        """A single missing </div> used to end the walk: 21 slides in, 10 out, and the exported
        PDF simply stopped in the middle of the deck with no error anywhere."""
        good = '<div class="slide"><div><p>%d</p></div></div>'
        broken = '<div class="slide"><div><p>broken</p></div>'
        html = '\n'.join([good % i for i in range(1, 11)] + [broken]
                         + [good % i for i in range(12, 22)])

        slides = extract_slide_elements(html)

        self.assertEqual(len(slides), 21)
        self.assertEqual(slides[-1], good % 21)
        # The repaired slide keeps its own content and closes itself.
        self.assertIn('broken', slides[10])
        self.assertTrue(slides[10].endswith('</div>'))
        self.assertEqual(slides[10].count('<div'), slides[10].count('</div'))

    def test_an_extra_closing_div_does_not_swallow_the_next_slide(self):
        html = ('<div class="slide"><div>one</div></div></div>'
                '<div class="slide"><div>two</div></div>')

        slides = extract_slide_elements(html)

        self.assertEqual(len(slides), 2)
        self.assertIn('two', slides[1])

    def test_a_slide_class_is_a_whole_class_not_a_substring(self):
        """`\\bslide\\b` also matches `slide-inner` (a hyphen is a word boundary), so one real slide
        was read as three fragments: an empty `<div class="slide"></div>` plus its own blocks."""
        html = ('<div class="slide"><div class="slide-inner"><p>one</p></div>'
                '<div class="slide-footer">f</div></div>')

        slides = extract_slide_elements(html)

        self.assertEqual(len(slides), 1)
        self.assertEqual(slides[0], html)
        # A class list still counts, and an unrelated class does not.
        self.assertEqual(len(extract_slide_elements('<div class="printable slide x"><i>a</i></div>')), 1)
        self.assertEqual(extract_slide_elements('<div class="slideshow"><i>a</i></div>'), [])

    def test_print_css_puts_every_slide_back_in_flow(self):
        """An out-of-flow slide gets no page of its own: measured 5 pages for 6 slides with one
        `position:absolute` slide, and 1 page for 6 when all of them had it."""
        source = (ROOT / 'generate_pdf_from_preview.py').read_text(encoding='utf-8')
        print_block = source[source.index('@media print {'):source.index('.pdf-export-page:last-of-type')]
        for rule in ('position:relative !important', 'float:none !important',
                     'display:block !important', 'break-after:page !important',
                     'page-break-after:always !important'):
            self.assertIn(rule, print_block, rule)

    def test_body_grid_cannot_combine_two_slides_on_one_page(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        slides = '\n'.join(
            '<div class="slide"><style>'
            'body{display:grid!important;grid-template-columns:1fr 1fr!important;columns:2!important}'
            '</style><p>slide</p></div>'
            for _ in range(6)
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'body-grid.pdf'
            with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                engine.generate_pdf(slides, {}, pdf_path)
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 6)

    def test_inline_important_position_cannot_remove_slide_pages(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        slides = '\n'.join(
            '<div class="slide"'
            + ('' if index % 2 == 0 else ' style="position:absolute!important"')
            + f'><p>{index}</p></div>'
            for index in range(6)
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'position-important.pdf'
            with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                engine.generate_pdf(slides, {}, pdf_path)
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 6)

    def test_fitz_fallback_keeps_one_page_per_slide(self):
        import sys
        import tempfile
        import types
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        playwright_stub = types.ModuleType('playwright.sync_api')
        playwright_stub.sync_playwright = lambda: (_ for _ in ()).throw(RuntimeError('forced failure'))
        slides = '\n'.join(f'<div class="slide"><p>{index}</p></div>' for index in range(6))
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'fitz-fallback.pdf'
            with patch.dict(sys.modules, {'playwright.sync_api': playwright_stub}):
                with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                    engine.generate_pdf(slides, {}, pdf_path)
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 6)

    def test_short_chromium_result_uses_isolated_playwright_pages(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        slides = '\n'.join(
            '<div class="slide" style="background:#0b4f6c!important"><style>'
            'body#pdf-export-root>.pdf-export-page{position:absolute!important}'
            '</style><p>slide</p></div>'
            for _ in range(6)
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'short-chromium.pdf'
            with patch.object(engine, '_generate_pdf_with_fitz', side_effect=AssertionError('unexpected fallback')):
                with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                    engine.generate_pdf(slides, {}, pdf_path)
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 6)
                red, green, blue = document[0].get_pixmap(alpha=False).pixel(20, 20)
                self.assertLess(red, 30)
                self.assertGreater(green, 60)
                self.assertGreater(blue, 90)

    def test_unclosed_table_cannot_swallow_following_chromium_pages(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        good = '<div class="slide" style="background:#0b4f6c!important"><p>good</p></div>'
        broken = ('<div class="slide" style="background:#0b4f6c!important">'
                  '<table><tbody><tr><td>broken</td>')
        slides = '\n'.join([good, broken, good, broken, good, good])
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'unclosed-table.pdf'
            with patch.object(engine, '_generate_pdf_with_fitz', side_effect=AssertionError('unexpected fallback')):
                with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                    engine.generate_pdf(slides, {}, pdf_path)
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 6)
                red, green, blue = document[1].get_pixmap(alpha=False).pixel(20, 20)
                self.assertLess(red, 30)
                self.assertGreater(green, 60)
                self.assertGreater(blue, 90)

    def test_a_short_pdf_is_an_error_not_a_smaller_export(self):
        import generate_pdf_from_preview as engine

        class _Doc:
            page_count = 24

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        import sys
        import types
        stub = types.ModuleType('fitz')
        stub.open = lambda *args, **kwargs: _Doc()
        original = sys.modules.get('fitz')
        sys.modules['fitz'] = stub
        try:
            with self.assertRaises(RuntimeError) as raised:
                engine._verify_pdf_page_count('deck.pdf', 49)
            self.assertIn('24', str(raised.exception))
            self.assertIn('49', str(raised.exception))
            # Equal or more pages is not a failure: a slide may overflow its own page.
            engine._verify_pdf_page_count('deck.pdf', 24)
            engine._verify_pdf_page_count('deck.pdf', 20)
        finally:
            if original is None:
                del sys.modules['fitz']
            else:
                sys.modules['fitz'] = original


if __name__ == '__main__':
    unittest.main()
