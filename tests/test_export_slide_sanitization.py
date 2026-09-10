import base64
import unittest
from pathlib import Path

from design_templates import extract_slide_elements
import slide_engine

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

    def test_export_keeps_media_contained_and_charts_within_the_page(self):
        source = (ROOT / 'generate_pdf_from_preview.py').read_text(encoding='utf-8')
        self.assertGreaterEqual(source.count('object-fit:contain'), 2)
        self.assertGreaterEqual(source.count('svg[data-chart], svg.combo-chart'), 2)

    def test_visual_media_grid_is_height_constrained_for_export(self):
        html = slide_engine._build_visual_concept_media_slide(
            {
                'title': 'مخطط الدور الأرضي',
                'section_key': 'plans',
                'content_source': 'plan_image:1',
                'image_tokens': ['##PLAN_IMAGE_1##'],
            },
            branding={},
        )
        self.assertIn(
            'position:absolute;top:126px;right:34px;bottom:48px;left:34px;',
            html,
        )
        self.assertIn('data-visual-media-frame="1" style="position:relative;', html)
        self.assertIn('position:absolute!important;inset:0!important;', html)
        self.assertIn('width:100%!important;height:100%!important;', html)
        self.assertIn('object-fit:contain!important;', html)

    def test_visual_media_image_stays_inside_frame_when_height_auto_is_forced(self):
        from playwright.sync_api import sync_playwright

        image_data = base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="847" height="597"></svg>'
        ).decode('ascii')
        html = slide_engine._build_visual_concept_media_slide(
            {
                'title': 'مخطط الدور الأرضي',
                'section_key': 'plans',
                'content_source': 'plan_image:1',
                'image_tokens': ['##PLAN_IMAGE_1##'],
            },
            branding={},
        ).replace('##PLAN_IMAGE_1##', f'data:image/svg+xml;base64,{image_data}')
        document = (
            '<!doctype html><style>'
            '*{margin:0;padding:0;box-sizing:border-box}'
            '.slide{display:block!important}'
            'img{height:auto!important}'
            '</style>' + html
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 720})
                page.set_content(document, wait_until='load')
                metrics = page.evaluate(
                    """() => {
                        const image = document.querySelector('[data-visual-media-image]');
                        const frame = document.querySelector('[data-visual-media-frame]');
                        const slide = document.querySelector('.slide');
                        const imageBox = image.getBoundingClientRect();
                        const frameBox = frame.getBoundingClientRect();
                        const slideBox = slide.getBoundingClientRect();
                        const style = getComputedStyle(image);
                        return {
                            image: [imageBox.left, imageBox.top, imageBox.right, imageBox.bottom],
                            frame: [frameBox.left, frameBox.top, frameBox.right, frameBox.bottom],
                            slide: [slideBox.left, slideBox.top, slideBox.right, slideBox.bottom],
                            position: style.position,
                            objectFit: style.objectFit,
                        };
                    }"""
                )
            finally:
                browser.close()

        for image_edge, frame_edge in zip(metrics['image'], metrics['frame']):
            self.assertAlmostEqual(image_edge, frame_edge, delta=1.1)
        self.assertGreaterEqual(metrics['frame'][0], metrics['slide'][0])
        self.assertGreaterEqual(metrics['frame'][1], metrics['slide'][1])
        self.assertLessEqual(metrics['frame'][2], metrics['slide'][2])
        self.assertLessEqual(metrics['frame'][3], metrics['slide'][3])
        self.assertEqual(metrics['position'], 'absolute')
        self.assertEqual(metrics['objectFit'], 'contain')

    def test_renumbering_migrates_legacy_visual_media_to_bounded_layout(self):
        legacy_html = (
            '<div class="slide" style="width:1280px;height:720px;overflow:hidden">'
            '<div data-legacy-media-frame><img src="/uploads/old.png" '
            'style="display:block;width:100%;height:auto"></div></div>'
        )
        slides = [
            {
                'title': 'مخطط الدور الأرضي',
                'type': 'content',
                'section_key': 'plans',
                'content_source': 'plan_image:1',
                'image_tokens': ['##PLAN_IMAGE_1##'],
                'html': legacy_html,
            },
            {
                'title': 'التصور الداخلي',
                'type': 'content',
                'section_key': 'interior',
                'content_source': 'interior_images_group:1:1:2',
                'image_tokens': ['##INTERIOR_COMP_1_IMG_1##', '##INTERIOR_COMP_1_IMG_2##'],
                'html': legacy_html,
            },
            {
                'title': 'التصور الخارجي',
                'type': 'content',
                'section_key': 'exterior',
                'content_source': 'exterior_image:1',
                'image_tokens': ['##MOODBOARD_IMAGE_1##'],
                'html': legacy_html,
            },
        ]
        creative_images = {
            'plans': [{'url': '/uploads/plan.png'}],
            'moodboard': [{'url': '/uploads/exterior.png'}],
            'interior_components': [{
                'images': [
                    {'url': '/uploads/interior-1.png'},
                    {'url': '/uploads/interior-2.png'},
                ],
            }],
        }

        migrated = slide_engine.renumber_presentation_slides(
            slides,
            branding={'primary_color': '#123456'},
            project_data={'project_name': 'المشروع'},
            creative_images=creative_images,
        )

        self.assertEqual(len(migrated), 3)
        for slide in migrated:
            self.assertIn('data-visual-media-only="1"', slide['html'])
            self.assertIn('data-visual-media-grid="1"', slide['html'])
            self.assertIn('position:absolute;top:126px;right:34px;bottom:48px;left:34px', slide['html'])
            self.assertIn('object-fit:contain!important', slide['html'])
            self.assertIn('position:absolute!important;inset:0!important', slide['html'])
            self.assertNotIn('data-legacy-media-frame', slide['html'])
            self.assertNotIn('height:auto', slide['html'])
        self.assertIn('/uploads/plan.png', migrated[0]['html'])
        self.assertIn('/uploads/interior-1.png', migrated[1]['html'])
        self.assertIn('/uploads/interior-2.png', migrated[1]['html'])
        self.assertIn('/uploads/exterior.png', migrated[2]['html'])
        self.assertEqual(
            migrated,
            slide_engine.renumber_presentation_slides(
                migrated,
                branding={'primary_color': '#123456'},
                project_data={'project_name': 'المشروع'},
                creative_images=creative_images,
            ),
        )

    def test_renumbering_recovers_legacy_plan_image_without_image_tokens(self):
        legacy_html = (
            '<div class="slide" style="width:1280px;height:720px;overflow:hidden">'
            '<div><img class="project-logo" src="/uploads/creative/tenant/project-logo.png"></div>'
            '<div><img src="/api/map-images/overview" style="width:100%;height:auto"></div>'
            '<div data-legacy-media-frame><img src="/uploads/creative/tenant/plan-floor-1.png" '
            'style="display:block;width:100%;height:auto"></div></div>'
        )
        slides = [{
            'title': 'مخطط الدور الأرضي',
            'type': 'content',
            'section_key': 'plans',
            'content_source': 'plan_image:1',
            'html': legacy_html,
        }]

        migrated = slide_engine.renumber_presentation_slides(
            slides,
            branding={'primary_color': '#123456'},
            project_data={'project_name': 'المشروع'},
            creative_images={},
        )

        self.assertEqual(len(migrated), 1)
        html = migrated[0]['html']
        self.assertIn('data-visual-media-only="1"', html)
        self.assertIn('data-visual-media-grid="1"', html)
        self.assertIn('/uploads/creative/tenant/plan-floor-1.png', html)
        self.assertNotIn('/uploads/creative/tenant/project-logo.png', html)
        self.assertNotIn('/api/map-images/overview', html)
        self.assertNotIn('data-legacy-media-frame', html)
        self.assertNotIn('height:auto', html)
        self.assertIn('position:absolute!important;inset:0!important', html)
        self.assertIn('object-fit:contain!important', html)

    def test_renumbering_prefers_plan_token_inferred_from_content_source(self):
        slides = [{
            'title': 'مخطط الدور الأرضي',
            'type': 'content',
            'section_key': 'plans',
            'content_source': 'plan_image:2',
            'image_tokens': ['##PLAN_IMAGE_1##'],
            'html': (
                '<div class="slide"><img src="/uploads/creative/tenant/stale-plan.png" '
                'style="width:100%;height:auto"></div>'
            ),
        }]

        migrated = slide_engine.renumber_presentation_slides(
            slides,
            branding={'primary_color': '#123456'},
            project_data={'project_name': 'المشروع'},
            creative_images={'plans': [
                {'url': '/uploads/creative/tenant/plan-1.png'},
                {'url': '/uploads/creative/tenant/current-plan-2.png'},
            ]},
        )

        self.assertEqual(migrated[0]['image_tokens'], ['##PLAN_IMAGE_2##'])
        self.assertIn('/uploads/creative/tenant/current-plan-2.png', migrated[0]['html'])
        self.assertNotIn('/uploads/creative/tenant/stale-plan.png', migrated[0]['html'])
        self.assertIn('object-fit:contain!important', migrated[0]['html'])

    def test_renumbering_keeps_non_media_plan_slide_content(self):
        original_html = (
            '<div class="slide"><p>تحليل توزيع المساحات</p>'
            '<img src="/uploads/creative/tenant/supporting-plan.png" style="width:45%;height:auto"></div>'
        )
        migrated = slide_engine.renumber_presentation_slides([{
            'title': 'تحليل المخططات',
            'type': 'content',
            'section_key': 'plans',
            'content_source': 'plan_notes',
            'html': original_html,
        }], branding={'primary_color': '#123456'}, project_data={'project_name': 'المشروع'})

        self.assertIn('تحليل توزيع المساحات', migrated[0]['html'])
        self.assertIn('/uploads/creative/tenant/supporting-plan.png', migrated[0]['html'])
        self.assertNotIn('data-visual-media-only="1"', migrated[0]['html'])

    def test_legacy_visual_media_token_alias_is_rebuilt(self):
        migrated = slide_engine.renumber_presentation_slides([{
            'title': 'التصور الخارجي',
            'type': 'content',
            'section_key': 'exterior',
            'image_tokens': ['##PROJECT_IMAGE_1##'],
            'html': '<div class="slide"></div>',
        }], branding={}, project_data={}, creative_images={
            'moodboard': [{'url': '/uploads/creative/tenant/exterior-1.png'}],
        })

        self.assertIn('/uploads/creative/tenant/exterior-1.png', migrated[0]['html'])
        self.assertIn('data-visual-media-only="1"', migrated[0]['html'])

    def test_slide_preview_matches_export_margin_reset(self):
        source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('display: block !important;', source)
        self.assertIn('transform: scale(var(--slide-scale, 0.75)) !important;', source)
        self.assertIn(
            '.tenant-slide-stage .slide * {\n'
            '      margin: 0;\n'
            '      padding: 0;\n'
            '      box-sizing: border-box;',
            source,
        )

    def test_authenticated_project_file_images_are_localized_for_export(self):
        """Legacy cover images and project logos use an authenticated route in the editor."""
        import tempfile
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            image_path = root / 'uploads' / 'tenant-a' / 'project-documents' / 'cover.png'
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b'not-rendered-by-this-unit-test')
            stored = {
                'storage_path': str(image_path),
                'mime_type': 'image/png',
            }
            html = (
                '<div class="slide" style="background-image:url(\'/api/project-files/file-1?cache=2\');">'
                '<img src="https://sagdemos.store/api/project-files/file-1" />'
                '</div>'
            )
            with patch.object(engine, 'BASE_DIR', root), \
                    patch('db.get_project_file', return_value=stored):
                resolved = engine._resolve_project_file_urls(html, 'tenant-a')

            local_uri = image_path.as_uri()
            self.assertIn(local_uri, resolved)
            self.assertNotIn('/api/project-files/file-1', resolved)

    def test_unresolvable_project_file_url_is_left_untouched(self):
        import tempfile
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        with tempfile.TemporaryDirectory():
            html = '<div class="slide"><img src="/api/project-files/missing"></div>'
            with patch('db.get_project_file', return_value=None):
                self.assertEqual(engine._resolve_project_file_urls(html, 'tenant-a'), html)

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

    def test_isolated_pdf_is_staged_on_the_output_filesystem(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_dir = Path(tmp_dir) / 'source'
            output_dir = Path(tmp_dir) / 'output'
            source_dir.mkdir()
            output_dir.mkdir()
            source_path = source_dir / 'merged.pdf'
            output_path = output_dir / 'deck.pdf'
            source_path.write_bytes(b'chromium pdf')
            original_replace = engine.os.replace
            with patch.object(engine.os, 'replace', wraps=original_replace) as replace:
                engine._replace_output_file(source_path, output_path)
            self.assertEqual(output_path.read_bytes(), b'chromium pdf')
            self.assertEqual(Path(replace.call_args.args[0]).parent, output_dir)

    def test_failed_isolated_chromium_never_returns_plain_fitz_output(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        slides = '\n'.join(
            '<div class="slide"><style>'
            'body#pdf-export-root>.pdf-export-page{position:absolute!important}'
            '</style><p>slide</p></div>'
            for _ in range(6)
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'failed-isolation.pdf'
            with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                with patch.object(engine, '_generate_pdf_pages_with_playwright', side_effect=RuntimeError('isolated failed')):
                    with patch.object(engine, '_generate_pdf_with_fitz', side_effect=AssertionError('unexpected fallback')) as fallback:
                        with self.assertRaisesRegex(RuntimeError, 'isolated failed'):
                            engine.generate_pdf(slides, {}, pdf_path)
                        fallback.assert_not_called()

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

    def test_visual_concept_captions_preserved_across_renumbering(self):
        """Visual concept captions added via designer chat or editing must survive multiple renumber passes."""
        caption_text = "واجهة زجاجية حديثة بتصميم بانورامي فخم"
        slide_html = (
            '<div class="slide" data-slide-role="visual-concept-media">'
            '  <div class="visual-media-card">'
            '    <img src="/api/media/visual_1.png">'
            f'    <div data-visual-media-caption="1">{caption_text}</div>'
            '  </div>'
            '</div>'
        )
        slide = {
            'type': 'content',
            'section_key': 'visual_concept',
            'content_source': 'visual_concept:1',
            'title': 'التصور البصري',
            'image_tokens': ['##VISUAL_CONCEPT_1##'],
            'html': slide_html,
            '_designer_keep_html': True,
        }

        # First pass (designer chat turn end)
        pass1 = slide_engine.renumber_presentation_slides([slide], project_data={'visual_concept': {'slots': {}}})
        self.assertEqual(len(pass1), 1)
        self.assertIn(caption_text, pass1[0]['html'])
        self.assertTrue(pass1[0].get('_designer_keep_html'))
        self.assertTrue(pass1[0].get('is_custom'))

        # Second pass (save presentation / save draft)
        pass2 = slide_engine.renumber_presentation_slides(pass1, project_data={'visual_concept': {'slots': {}}})
        self.assertEqual(len(pass2), 1)
        self.assertIn(caption_text, pass2[0]['html'])
        self.assertTrue(pass2[0].get('_designer_keep_html'))
        self.assertTrue(pass2[0].get('is_custom'))

        # Third pass (reload presentation / preview / export)
        pass3 = slide_engine.renumber_presentation_slides(pass2, project_data={'visual_concept': {'slots': {}}})
        self.assertEqual(len(pass3), 1)
        self.assertIn(caption_text, pass3[0]['html'])
        self.assertTrue(pass3[0].get('_designer_keep_html'))
        self.assertTrue(pass3[0].get('is_custom'))

    def test_visual_concept_captions_extracted_and_restored_if_rebuilt(self):
        """Even if flags are absent, captions in HTML are extracted and preserved on rebuild."""
        caption_text = "بهو استقبال رئيسي بأسقف مزدوجة الارتفاع"
        slide_html = (
            '<div class="slide" data-slide-role="visual-concept-media">'
            '  <div class="visual-media-card">'
            '    <img src="/api/media/visual_2.png">'
            f'    <div data-visual-media-caption="1">{caption_text}</div>'
            '  </div>'
            '</div>'
        )
        extracted = slide_engine._extract_visual_concept_captions(slide_html)
        self.assertEqual(extracted, [caption_text])

        slide_to_rebuild = {
            'type': 'content',
            'section_key': 'visual_concept',
            'content_source': 'visual_concept:2',
            'title': 'التصور البصري',
            'image_tokens': ['##VISUAL_CONCEPT_2##'],
            'html': slide_html,
        }
        rebuilt = slide_engine._build_visual_concept_media_slide(slide_to_rebuild)
        self.assertIn(caption_text, rebuilt)
        self.assertEqual(slide_to_rebuild.get('captions'), [caption_text])

    def test_chromium_launcher_uses_configured_system_binary_when_bundled_fails(self):
        """A host whose bundled Chromium cannot start (missing OS libraries) still
        exports faithfully when the admin points CHROMIUM_PATH at a working binary."""
        import os
        import tempfile
        import types
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        calls = []

        class _StubChromium:
            def launch(self, *args, **kwargs):
                calls.append(kwargs)
                if kwargs.get('executable_path') == fake_path:
                    return object()
                raise RuntimeError('missing shared libraries')

        stub = types.SimpleNamespace(chromium=_StubChromium())
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_path = os.path.join(tmp_dir, 'chrome')
            with open(fake_path, 'wb') as handle:
                handle.write(b'fake')
            with patch.dict(os.environ, {'CHROMIUM_PATH': fake_path, 'CHROME_PATH': ''}):
                browser, how = engine._launch_chromium(stub)
        self.assertIsNotNone(browser)
        self.assertIn('system-chromium', how)
        self.assertIn(fake_path, how)
        self.assertTrue(any('executable_path' not in call for call in calls))

    def test_chromium_launcher_names_every_attempt_when_nothing_starts(self):
        import os
        import types
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        class _StubChromium:
            def launch(self, *args, **kwargs):
                raise RuntimeError('missing shared libraries')

        stub = types.SimpleNamespace(chromium=_StubChromium())
        with patch.dict(os.environ, {'CHROMIUM_PATH': '', 'CHROME_PATH': ''}, clear=False):
            with patch.object(engine, '_chromium_executable_candidates', return_value=[]):
                with self.assertRaises(RuntimeError) as raised:
                    engine._launch_chromium(stub)
        self.assertIn('bundled', str(raised.exception))
        self.assertIn('bundled-single-process', str(raised.exception))
        self.assertIn('bundled-headless-new', str(raised.exception))

    def test_chromium_launcher_prefers_single_process_rescue(self):
        """A bundled binary that dies on the default spawn may still run
        single-process without zygote — the known restricted-container rescue."""
        import types

        import generate_pdf_from_preview as engine

        class _StubChromium:
            def launch(self, *args, **kwargs):
                args = kwargs.get('args') or []
                if '--single-process' in args:
                    return object()
                raise RuntimeError('Target page, context or browser has been closed')

        stub = types.SimpleNamespace(chromium=_StubChromium())
        browser, how = engine._launch_chromium(stub)
        self.assertIsNotNone(browser)
        self.assertEqual(how, 'bundled-chromium-single-process')

    def test_headless_new_attempt_restores_environment(self):
        import os
        import types
        from unittest.mock import patch

        import generate_pdf_from_preview as engine

        class _StubChromium:
            def launch(self, *args, **kwargs):
                raise RuntimeError('missing shared libraries')

        stub = types.SimpleNamespace(chromium=_StubChromium())
        with patch.dict(os.environ, {'CHROMIUM_PATH': '', 'CHROME_PATH': ''}, clear=False):
            os.environ.pop('PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW', None)
            with patch.object(engine, '_chromium_executable_candidates', return_value=[]):
                with self.assertRaises(RuntimeError):
                    engine._launch_chromium(stub)
            self.assertNotIn('PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW', os.environ)

    def test_browser_error_keeps_the_diagnosis_tail(self):
        """Playwright opens with hundreds of chars of flags and names the missing
        library at the end — the slice must keep the tail, not just the head."""
        import generate_pdf_from_preview as engine

        message = 'BrowserType.launch: ' + ' '.join(f'--flag-{n}' for n in range(80))
        message += ' Host system is missing dependencies: libnss3.so libatk.so'
        shortened = engine.short_browser_error(RuntimeError(message))
        self.assertIn('BrowserType.launch', shortened)
        self.assertIn('libnss3.so', shortened)
        self.assertLessEqual(len(shortened), 130 + 260 + 10)

    def test_fallback_marks_degraded_engine(self):
        """The PyMuPDF fallback keeps the page count but shifts the layout, so the
        export must record which engine wrote the file instead of passing silently."""
        import sys
        import tempfile
        import types
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        playwright_stub = types.ModuleType('playwright.sync_api')
        playwright_stub.sync_playwright = lambda: (_ for _ in ()).throw(RuntimeError('forced failure'))
        slides = '\n'.join(f'<div class="slide"><p>{index}</p></div>' for index in range(3))
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'fitz-engine.pdf'
            with patch.dict(sys.modules, {'playwright.sync_api': playwright_stub}):
                with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                    engine.generate_pdf(slides, {}, pdf_path)
            self.assertEqual(engine.LAST_PDF_ENGINE, 'fitz-fallback')
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 3)

    def test_chromium_export_marks_faithful_engine(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import fitz
        import generate_pdf_from_preview as engine

        slides = '\n'.join(f'<div class="slide"><p>{index}</p></div>' for index in range(3))
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / 'chromium-engine.pdf'
            with patch.object(engine, 'build_font_css', return_value=('', 'Arial')):
                engine.generate_pdf(slides, {}, pdf_path)
            self.assertIn(engine.LAST_PDF_ENGINE, ('chromium', 'chromium-isolated'))
            with fitz.open(pdf_path) as document:
                self.assertEqual(document.page_count, 3)


if __name__ == '__main__':
    unittest.main()
