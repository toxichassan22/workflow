import unittest

from design_templates import extract_slide_elements


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
