"""Black-box source-preservation and adversarial color-editor regressions."""
import unittest

from designer_chat_colors import (
    NOT_APPLICABLE, REFUSAL_PREFIX, apply_color_edit,
    color_only_content_preserved, is_color_only_request, parse_color_edit,
)


class ColorRequestTests(unittest.TestCase):
    def test_explicit_source_and_target_equivalents(self):
        requests = [
            'استبدل اللون الأحمر باللون الأزرق',
            'غير الأحمر إلى الأزرق', 'بدل #f00 بـ #00f',
            'استبدل rgb(255, 0, 0) باللون الأزرق',
            'replace red with blue', 'change #ff0000 to rgb(0 0 255)',
        ]
        source = '<div class="slide" style="color:RED">نص</div>'
        for request in requests:
            with self.subTest(request=request):
                result, message = apply_color_edit(source, request)
                self.assertEqual(result, source.replace('color:RED', 'color:#0000ff'), message)

    def test_arabic_scopes_and_politeness(self):
        for request, scope in [
            ('من فضلك اجعل خلفية الشريحة بيضاء فقط', 'background'),
            ('غير لون النص إلى الأبيض', 'text'),
            ('خلي كل النصوص باللون الكحلي', 'text'),
            ('لون العناوين باللون الأحمر', 'headings'),
            ('اجعل العناوين ذهبية', 'headings'),
            ('set background to navy', 'background'),
        ]:
            with self.subTest(request=request):
                edit, message = parse_color_edit(request)
                self.assertIsNotNone(edit, message)
                self.assertEqual(edit.scope, scope)

    def test_ambiguous_color_requests_refuse_without_guessing(self):
        for request in [
            'غير الألوان', 'خلي الألوان أجمل', 'غير اللون إلى الأزرق',
            'اجعل الخلفية أزرق فاتح', 'استبدل الأحمر بالأزرق أو الأخضر',
            'غير خلفية الجدول إلى الأحمر', 'اجعل العنوان الأول باللون الأحمر',
            'اجعل النص بلون الشركة', 'change background to #12345',
            'replace red with rgb(999,0,0)', 'replace red with var(--brand)',
            'replace red with blue; width:0', 'اجعل الخلفية بيضاء والنص أسود',
        ]:
            with self.subTest(request=request):
                result, message = apply_color_edit('<div style="color:red">نص</div>', request)
                self.assertIsNone(result)
                self.assertTrue(message.startswith(REFUSAL_PREFIX), message)

    def test_unrelated_and_mixed_requests_not_applicable(self):
        for request in [None, '', 'أعد صياغة الفقرة', 'احذف الشريحة',
                        'غير لون النص للأحمر وكبر حجم العنوان',
                        'replace red with blue and delete the table']:
            with self.subTest(request=request):
                self.assertFalse(is_color_only_request(request))
                self.assertEqual(apply_color_edit('untouched', request), (None, NOT_APPLICABLE))


class ColorEditingTests(unittest.TestCase):
    def apply(self, source, request='replace red with blue'):
        result, message = apply_color_edit(source, request)
        self.assertIsNotNone(result, message)
        self.assertTrue(color_only_content_preserved(source, result))
        return result

    def test_inline_css_preserves_every_other_byte(self):
        source = '''<!doctype html>
<DIV class='slide' data-name="red #f00" style="width:1280px; COLOR : #F00 !important; height:720px">
<h1 title='red'>الأحمر #f00</h1><table style='border: 2px solid rgb(255,0,0)'><tr><td>1,234.5</td></tr></table>
<img src="https://example.test/red.png#f00" style="background-color:red;width:48px">
<a href='#f00' style='color:red'>red</a><!-- color:red -->
<script>const x = '<b style="color:red">red</b>';</script></DIV>'''
        expected = source.replace('COLOR : #F00', 'COLOR : #0000ff').replace(
            'solid rgb(255,0,0)', 'solid #0000ff').replace("style='color:red'", "style='color:#0000ff'")
        self.assertEqual(self.apply(source), expected)

    def test_style_blocks_selectors_comments_and_media_rules_preserved(self):
        source = '''<style>
/* red #f00 */ .slide { color: red; width:1280px }
@media print { .slide h1 {border-color: #f00; font-size:32px} }
@supports (display: grid) { @layer paint { .slide .body {color:rgb(255 0 0)} } }
#red, .unused {color:red} .slide::before{content:'red';color:red}
</style><div class="slide"><h1>Title</h1><p class="body">Body</p></div>'''
        expected = source.replace('color: red;', 'color: #0000ff;').replace(
            'border-color: #f00', 'border-color: #0000ff').replace('color:rgb(255 0 0)', 'color:#0000ff')
        self.assertEqual(self.apply(source), expected)

    def test_urls_strings_attributes_scripts_and_custom_properties_immutable(self):
        source = '''<style>.slide {color:red;
background:url("data:image/svg+xml;utf8,<svg fill='red'>#f00</svg>") red;
background-image: url(https://example.test/red.png#f00);
--brand:red; content:"red #f00"; font-family:red; animation-name:red;
filter:drop-shadow(0 0 2px red); fill:red; stroke:red;
}</style><div class="slide" data-x='style="color:red"' title="red">
<textarea>&lt;p style="color:red"&gt;</textarea><script>color:red</script>red</div>'''
        expected = source.replace('{color:red;', '{color:#0000ff;').replace('</svg>\") red;', '</svg>\") #0000ff;')
        self.assertEqual(self.apply(source), expected)

    def test_gradients_and_shadows_replace_only_color_tokens(self):
        source = '''<div class="slide" style="background:linear-gradient(45deg, red 20%, #f00 70%, blue), url(red.png);box-shadow:1px 2px 3px 4px red; text-shadow:0 1px #f00; border:2px solid red">1</div>'''
        expected = source.replace('red 20%', '#0000ff 20%').replace('#f00 70%', '#0000ff 70%').replace(
            '4px red', '4px #0000ff').replace('1px #f00', '1px #0000ff').replace('solid red', 'solid #0000ff')
        self.assertEqual(self.apply(source), expected)

    def test_hex_alpha_and_rgba_are_not_conflated_with_opaque_colors(self):
        source = '<div style="color:rgba(255,0,0,.5);background:#ff000080;border-color:#f00f">x</div>'
        self.assertEqual(self.apply(source), source.replace('#f00f', '#0000ff'))
        result = self.apply(source, 'replace rgba(255,0,0,.5) with rgba(0,0,255,.25)')
        self.assertIn('color:rgba(0,0,255,0.25)', result)
        self.assertIn('background:#ff000080', result)

    def test_percent_rgb_matches_canonical_hex(self):
        source = '<div style="color:rgb(100%,0%,0%)">x</div>'
        self.assertEqual(self.apply(source), source.replace('rgb(100%,0%,0%)', '#0000ff'))

    def test_logo_and_image_backgrounds_are_independently_protected(self):
        source = '''<style>
.slide .tile {background:red}
.logo {background:red} img {background:red} .body, img {color:red}
</style><div class="slide" style="background:white;color:red">
<div class="company-logo" style="background:red"><span style="color:red">L</span></div>
<div data-project-logo="1" style="background:red">P</div>
<img style="background:red" src="logo.png"><p class="tile" style="color:red">Text</p></div>'''
        expected = source.replace('.tile {background:red}', '.tile {background:#0000ff}').replace(
            'background:white;color:red', 'background:white;color:#0000ff').replace(
            'class="tile" style="color:red"', 'class="tile" style="color:#0000ff"')
        self.assertEqual(self.apply(source), expected)

    def test_scoped_background_does_not_change_cards_or_text(self):
        source = '''<style>.slide{background-color:red}.card{background:red;color:red}</style><div class="slide"><div class="card">x</div></div>'''
        self.assertEqual(self.apply(source, 'اجعل خلفية الشريحة بيضاء'),
                         source.replace('background-color:red', 'background-color:#ffffff'))

    def test_scoped_background_refuses_gradient_instead_of_flattening(self):
        source = '<div class="slide" style="background:linear-gradient(red,blue)">x</div>'
        result, message = apply_color_edit(source, 'اجعل الخلفية بيضاء')
        self.assertIsNone(result)
        self.assertTrue(message.startswith(REFUSAL_PREFIX))

    def test_scoped_headings_does_not_change_other_selectors(self):
        source = '''<style>.slide h1{color:red}.body{color:red}</style><div class="slide" style="color:red"><h1>Title</h1><div class="slide-title" style="color:gold">Title 2</div><p class="body">Text</p></div>'''
        expected = source.replace('h1{color:red}', 'h1{color:#0000ff}').replace('color:gold', 'color:#0000ff')
        self.assertEqual(self.apply(source, 'اجعل العناوين زرقاء'), expected)

    def test_scoped_text_preserves_every_background_and_border(self):
        source = '<div class="slide" style="color:red;background:red"><h1 style="color:gold;border:1px solid red">x</h1><p style="color:black">text</p></div>'
        expected = source.replace('color:red', 'color:#ffffff').replace('color:gold', 'color:#ffffff').replace('color:black', 'color:#ffffff')
        self.assertEqual(self.apply(source, 'غير لون النص إلى الأبيض'), expected)

    def test_missing_source_and_inherited_heading_refuse(self):
        for source, request in [
            ('<div style="color:black">x</div>', 'replace red with blue'),
            ('<div class="slide"><h1>Title</h1></div>', 'اجعل العناوين زرقاء'),
            ('<div style="color:var(--brand, red)">x</div>', 'replace red with blue'),
        ]:
            with self.subTest(source=source):
                result, message = apply_color_edit(source, request)
                self.assertIsNone(result)
                self.assertTrue(message.startswith(REFUSAL_PREFIX))

    def test_noop_returns_original_bytes(self):
        source = '<div style="color:RED !important">x</div>'
        self.assertEqual(self.apply(source, 'replace red with #ff0000'), source)

    def test_encoded_css_and_non_css_style_blocks_are_immutable(self):
        source = '''<style type="text/plain">.slide{color:red}</style><div class="slide" style="color:r&#101;d"><p style="color:red">x</p></div>'''
        self.assertEqual(self.apply(source), source.replace('<p style="color:red">', '<p style="color:#0000ff">'))

    def test_malformed_html_css_and_duplicate_attributes_fail_closed(self):
        for source in [
            '<div style="color:red">x', '<div><p style="color:red">x</div>',
            '<div style="color:red" STYLE="color:blue">x</div>',
            '<div style="color:red;background:url(foo">x</div>',
            '<div style="color:red;/* unclosed">x</div>',
            '<style>.slide{color:red</style><div class="slide">x</div>',
        ]:
            with self.subTest(source=source):
                result, message = apply_color_edit(source, 'replace red with blue')
                self.assertIsNone(result)
                self.assertTrue(message.startswith(REFUSAL_PREFIX))


class PreservationGuardTests(unittest.TestCase):
    SOURCE = '''<style>.slide h1{color:red;font-size:32px}.logo{background:white}</style><div class="slide" style="width:1280px;height:720px;background:white"><h1>Title</h1><table><tr><td style="color:black">1,234.5</td></tr></table><img class="logo" src="map.png" style="background:white;width:48px"></div>'''

    def test_accepts_literal_colors_only_and_unchanged_source(self):
        self.assertTrue(color_only_content_preserved(self.SOURCE, self.SOURCE))
        edited = self.SOURCE.replace('color:red', 'color:rgb(0, 0, 255)').replace('color:black', 'color:#333')
        self.assertTrue(color_only_content_preserved(self.SOURCE, edited))

    def test_rejects_every_noncolor_mutation_even_with_valid_color_change(self):
        edits = [
            ('Title', 'New title'), ('1,234.5', '1,235'), ('map.png', 'other.png'),
            ('width:1280px', 'width:1200px'), ('height:720px', 'height:600px'),
            ('font-size:32px', 'font-size:48px'), ('.slide h1', '.slide'),
            ('<table>', '<table style="display:none">'), ('<td ', '<th '),
            ('color:black', 'color:blue;opacity:0'), ('color:black', 'display:none'),
            ('color:black', 'color:var(--blue)'), ('color:black', 'color:blue !important'),
            ('background:white;width:48px', 'background:black;width:48px'),
            ('.logo{background:white}', '.logo{background:black}'),
            ('</div>', '<p>added</p></div>'), ('<h1>Title</h1>', ''),
            ('<img class="logo" src="map.png" style="background:white;width:48px">', ''),
            ('color:black', 'COLOR:black'),
        ]
        for old, new in edits:
            with self.subTest(change=(old, new)):
                after = self.SOURCE.replace('color:red', 'color:blue').replace(old, new)
                self.assertFalse(color_only_content_preserved(self.SOURCE, after))

    def test_rejects_color_in_non_css_or_custom_property_or_url(self):
        for source in [
            '<p title="red">red</p>', '<div style="--brand:red">x</div>',
            '<div style="background:url(red.png)">x</div>',
            '<style>.x::before{content:"red"}</style><p class="x">x</p>',
            '<script>const color="red";</script>', '<img style="background:red" src="x">',
            '<div style="color:var(--red, red)">x</div>',
        ]:
            with self.subTest(source=source):
                self.assertFalse(color_only_content_preserved(source, source.replace('red', 'blue')))

    def test_empty_invalid_and_non_string_fail_closed(self):
        for before, after in [(None, None), ('', ''), ('  ', '  '), ('<div>', '<div>'), (self.SOURCE, None)]:
            self.assertFalse(color_only_content_preserved(before, after))


if __name__ == '__main__':
    unittest.main()
