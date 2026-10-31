"""A slide the client or the designer chat edited keeps that edit on save.

Deterministic slides (index, dividers, cover, timeline) used to be rebuilt from
their canonical builders during every save, renumber and export, so an edit on
them landed in the workspace and reverted the moment the deck was stored. The
owner rule: any slide, generated or dragged in, is freely editable — chrome,
logo, text and numbers included. Renumbering may refresh managed numbers; it
must not replace the client's design.
"""

import re
import unittest

import slide_engine


BRANDING = {
    'primary_color': '#123B6D', 'secondary_color': '#0b1f33',
    'accent_color': '#C4A35A', 'background_color': '#ffffff',
    'text_color': '#111111', 'company_name': 'شركة الاختبار',
}
PROJECT = {'project_name': 'مشروع الفهرس'}


def _cover():
    return {'title': 'الغلاف', 'type': 'cover', 'html': '<div class="slide">غلاف</div>'}


def _index(html, **extra):
    return dict({'title': 'محتويات العرض', 'type': 'index', 'html': html}, **extra)


def _content(title, section, html, **extra):
    return dict({'title': title, 'type': 'content', 'section_key': section, 'html': html}, **extra)


def _closing():
    return {'title': 'الخاتمة', 'type': 'closing', 'html': '<div class="slide">ختام</div>'}


def _renumber(slides, **kwargs):
    kwargs.setdefault('branding', BRANDING)
    kwargs.setdefault('project_data', PROJECT)
    return slide_engine.renumber_presentation_slides(slides, **kwargs)


class DeterministicSlideEditsTests(unittest.TestCase):
    def test_a_designed_index_keeps_its_layout_and_still_renumbers(self):
        designed = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'background:#0b1f33;color:#ffffff;">'
            '<div style="font-size:40px;">INDEX-DESIGN-MARKER</div>'
            '<div data-index-section="overview"><span>نبذة موسعة</span>'
            '<span data-index-page="overview" dir="ltr">03</span></div>'
            '<div data-index-section="land"><span>الأرض</span>'
            '<span data-index-page="land" dir="ltr">04</span></div>'
            '</div>'
        )
        slides = [
            _cover(),
            _index(designed, is_custom=True, _designer_keep_html=True),
            _content('نبذة عن المشروع', 'overview', '<div class="slide">محتوى 1</div>'),
            _content('بيانات الأرض', 'land', '<div class="slide">محتوى 2</div>'),
            _closing(),
        ]
        out = _renumber(slides)
        index_html = out[1]['html']
        self.assertIn('INDEX-DESIGN-MARKER', index_html)
        self.assertIn('background:#0b1f33', index_html)
        self.assertIn('نبذة موسعة', index_html)
        # The page numbers still follow the deck's real positions.
        self.assertRegex(index_html, r'data-index-page="overview"[^>]*>03')
        self.assertRegex(index_html, r'data-index-page="land"[^>]*>04')
        # Saving twice is stable: no rebuild creeps back in.
        self.assertEqual(index_html, _renumber(out)[1]['html'])

    def test_a_designed_index_without_canonical_rows_is_left_alone(self):
        free_design = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;'
            'background:#ffffff;">'
            '<div class="free-index-grid">FREE-INDEX-DESIGN</div></div>'
        )
        out = _renumber([
            _cover(), _index(free_design, is_custom=True),
            _content('نبذة عن المشروع', 'overview', '<div class="slide">محتوى</div>'),
            _closing(),
        ])
        self.assertIn('FREE-INDEX-DESIGN', out[1]['html'])
        self.assertNotIn('data-index-section="overview"', out[1]['html'])

    def test_a_collapsed_designed_index_is_rebalanced_not_replaced(self):
        def row(key, text, page):
            return (f'<div data-index-section="{key}"><div>{text}</div>'
                    f'<div data-index-page="{key}" dir="ltr">{page}</div></div>')
        collapsed = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
            '<div style="display:grid;grid-template-columns:1fr 1fr;">'
            '<div>' + row('overview', 'نبذة', '03') + row('land', 'أرض', '04')
            + row('location', 'موقع', '05') + '</div><div></div></div>'
            '<div>COLLAPSED-INDEX-DESIGN</div></div>'
        )
        out = _renumber([
            _cover(), _index(collapsed, is_custom=True),
            _content('نبذة عن المشروع', 'overview', '<div class="slide">1</div>'),
            _content('بيانات الأرض', 'land', '<div class="slide">2</div>'),
            _content('موقع المشروع', 'location', '<div class="slide">3</div>'),
            _closing(),
        ])
        index_html = out[1]['html']
        self.assertIn('COLLAPSED-INDEX-DESIGN', index_html)
        self.assertIn('</div><div><div data-index-section="location"', index_html)
        self.assertRegex(index_html, r'data-index-page="location"[^>]*>05')

    def test_a_renamed_market_divider_keeps_its_title(self):
        divider_html = (
            '<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
            '<div>سوق المشروع — نسخة العميل</div><div>DIVIDER-DESIGN</div></div>'
        )
        out = _renumber([
            _cover(), _index('<div class="slide">فهرس</div>'),
            {'title': 'سوق المشروع — نسخة العميل', 'type': 'section_divider',
             'section_key': 'market', 'html': divider_html,
             'is_custom': True, '_designer_keep_html': True},
            _content('تحليل السوق', 'market', '<div class="slide">سوق</div>'),
            _closing(),
        ])
        self.assertEqual(out[2]['title'], 'سوق المشروع — نسخة العميل')
        self.assertIn('DIVIDER-DESIGN', out[2]['html'])
        self.assertEqual(out[2]['section_key'], 'market')

    def test_a_cover_edited_without_its_photo_is_not_replanted(self):
        cover_html = ('<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
                      '<div>غلاف من تصميم العميل</div></div>')
        out = _renumber(
            [dict(_cover(), html=cover_html, is_custom=True, _designer_keep_html=True),
             _index('<div class="slide">فهرس</div>'),
             _content('نبذة عن المشروع', 'overview', '<div class="slide">محتوى</div>'),
             _closing()],
            creative_images={'cover': '/uploads/creative/t/cover.png'})
        self.assertNotIn('data-cover-background', out[0]['html'])

    def test_a_second_timeline_gantt_slide_is_not_dropped(self):
        gantt = ('<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
                 '<div data-timeline-gantt="1">GANTT</div></div>')
        out = _renumber([
            _cover(), _index('<div class="slide">فهرس</div>'),
            _content('الجدول الزمني', 'timeline', gantt),
            _content('الجدول الزمني — نسخة', 'timeline', gantt,
                     is_custom=True, duplicated_from='s_source'),
            _closing(),
        ])
        self.assertEqual(len(out), 5)
        self.assertTrue(any('نسخة' in str(s.get('title')) for s in out))

    def test_an_edited_header_on_a_content_slide_survives_the_save(self):
        edited = ('<div class="slide" dir="rtl" style="width:1280px;height:720px;">'
                  '<div data-slide-header="1"><span>HEADER-EDIT</span></div>'
                  '<div>محتوى</div></div>')
        out = _renumber([
            _cover(), _index('<div class="slide">فهرس</div>'),
            _content('نبذة عن المشروع', 'overview', edited,
                     is_custom=True, _designer_keep_html=True),
            _closing(),
        ])
        self.assertIn('HEADER-EDIT', out[2]['html'])

    def test_an_unedited_index_still_gets_the_canonical_build(self):
        out = _renumber([
            _cover(), _index('<div class="slide"></div>'),
            _content('نبذة عن المشروع', 'overview', '<div class="slide">محتوى</div>'),
            _closing(),
        ])
        self.assertRegex(out[1]['html'], r'data-index-page="overview"[^>]*>03')


class ClientEditMarkersTests(unittest.TestCase):
    """Every manual/AI mutation must flag the slide, or the save rebuilds it."""

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        self.root = root
        self.undo = (root / 'assets' / 'js' / '14-slides-gen' / '01_undo.js').read_text(encoding='utf-8')

    def _source(self, relative):
        return (self.root / 'assets' / 'js' / relative).read_text(encoding='utf-8')

    def test_the_marker_helper_exists(self):
        self.assertIn('function markSlideHtmlEdited', self.undo)

    def test_every_manual_mutation_flags_the_slide(self):
        cases = {
            '15-slide-edit-chat/01_render_inline_edit.js': [
                'commitSlideInlineEdit', 'addSlideImageFromDevice', 'removeTenantSlideBackground'],
            '13-visual/02a_slide_element_drag.js': ['commitSlideElementMove', 'commitSlideElementDelete'],
            '15b-slide-canvas/04_authoring.js': [
                'insertSlideShape', 'insertSlideTable', 'mutateSlideTableSelection', 'setSlideRootStyles'],
            '15b-slide-canvas/02_snap_selection.js': ['commitSlideDragEntries'],
            '15b-slide-canvas/01_zoom_inspector.js': [
                'withSlideElementTargets', 'deleteSelectedSlideElements', 'pasteSlideElements',
                'ungroupSelectedSlideElements'],
            '14-slides-gen/02_element_editing.js': [
                'commitSlideElementResize', 'commitSlideElementColor', 'commitSlideElementOpacity',
                'toggleSlideElementBold', 'adjustSlideElementFontSize'],
            '15a-slide-workspace/01_workspace.js': ['commitTenantSlideRename'],
        }
        for relative, functions in cases.items():
            source = self._source(relative)
            for function in functions:
                marker = f'function {function}('
                self.assertIn(marker, source, f'{function} not found in {relative}')
                body = source.split(marker, 1)[1]
                body = re.split(r'\n    function ', body, maxsplit=1)[0]
                self.assertIn('markSlideHtmlEdited', body,
                              f'{function} in {relative} must flag the slide')

    def test_the_client_renumber_keeps_a_preserved_index_and_divider(self):
        source = self._source('13-visual/02_slides_progress.js')
        index_block = source.split("if (type === 'index')", 1)[1]
        self.assertIn('is_custom', index_block)
        self.assertIn('_designer_keep_html', index_block)
        gantt_block = source.split('function collapseDuplicateTimelineGantts', 1)[1]
        gantt_block = gantt_block.split('function renumberTenantSlides', 1)[0]
        self.assertIn('duplicated_from', gantt_block)


if __name__ == '__main__':
    unittest.main()
