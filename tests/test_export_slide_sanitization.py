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

    def test_ignores_unbalanced_slide(self):
        self.assertEqual(extract_slide_elements('<div class="slide"><div>broken</div>'), [])


if __name__ == '__main__':
    unittest.main()
