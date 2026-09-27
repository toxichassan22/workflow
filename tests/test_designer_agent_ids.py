import copy
import re
import unittest

import designer_agent_ids
import designer_chat_safety


def slide(inner, title='شريحة'):
    return {'title': title, 'type': 'content',
            'html': f'<div class="slide" dir="rtl" style="width:1280px;height:720px;">{inner}</div>'}


class SlideIdTests(unittest.TestCase):
    def test_new_slide_id_format(self):
        sid = designer_agent_ids.new_slide_id()
        self.assertTrue(re.fullmatch(r's_[0-9a-f]{8}', sid))

    def test_backfills_missing_ids_and_keeps_valid_ones(self):
        slides = [{'html': '<p>1</p>'}, {'id': 's_abc12345', 'html': '<p>2</p>'},
                  {'id': '', 'html': '<p>3</p>'}, {'html': '<p>4</p>'}]
        out = designer_agent_ids.ensure_slide_ids(slides)
        self.assertIs(out, slides)
        self.assertEqual(slides[1]['id'], 's_abc12345')
        ids = [s['id'] for s in slides]
        self.assertTrue(all(re.fullmatch(r's_[0-9a-f]{8}', i) for i in ids))
        self.assertEqual(len(set(ids)), len(ids))

    def test_duplicate_ids_deduped_first_wins(self):
        slides = [{'id': 's_aaaabbbb', 'html': 'a'}, {'id': 's_aaaabbbb', 'html': 'b'},
                  {'id': 's_aaaabbbb', 'html': 'c'}]
        designer_agent_ids.ensure_slide_ids(slides)
        self.assertEqual(slides[0]['id'], 's_aaaabbbb')
        self.assertNotEqual(slides[1]['id'], 's_aaaabbbb')
        self.assertNotEqual(slides[2]['id'], 's_aaaabbbb')
        self.assertNotEqual(slides[1]['id'], slides[2]['id'])

    def test_idempotent(self):
        slides = [slide('<p>x</p>') for _ in range(3)]
        designer_agent_ids.ensure_slide_ids(slides)
        before = [s['id'] for s in slides]
        designer_agent_ids.ensure_slide_ids(slides)
        self.assertEqual(before, [s['id'] for s in slides])

    def test_index_by_id(self):
        slides = [slide('<p>1</p>'), slide('<p>2</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        index = designer_agent_ids.index_by_id(slides)
        self.assertEqual(index[slides[0]['id']], 0)
        self.assertEqual(index[slides[1]['id']], 1)
        slides.insert(0, {'id': 's_zzzzzzzz', 'html': 'x'})
        index = designer_agent_ids.index_by_id(slides)
        self.assertEqual(index[slides[1]['id']], 1)

    def test_ids_survive_renumber_like_copy(self):
        """renumber_presentation_slides dict-copies each slide — ids ride along."""
        slides = [slide('<p>a</p>'), slide('<p>b</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        renumbered = [dict(s, slide_number=i + 1) for i, s in enumerate(reversed(slides))]
        self.assertEqual(renumbered[0]['id'], slides[1]['id'])
        self.assertEqual(renumbered[1]['id'], slides[0]['id'])

    def test_deck_signature_changes_on_edit_not_on_reorder_noise(self):
        slides = [slide('<p>a</p>'), slide('<p>b</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        sig = designer_agent_ids.deck_signature(slides)
        self.assertEqual(sig, designer_agent_ids.deck_signature(copy.deepcopy(slides)))
        slides[0]['html'] += '<p>changed</p>'
        self.assertNotEqual(sig, designer_agent_ids.deck_signature(slides))


class StructuralIdTests(unittest.TestCase):
    """Structural ops keep identities stable: no two live slides share an id."""

    def editor(self, html, title, instruction, index, kind, total, source):
        return html + '<!-- touched -->', 'تم'

    def test_split_gives_each_extra_part_a_new_id(self):
        import designer_chat_reliability as reliability
        source = slide(
            '<h2>الملخص</h2><div class="grid">'
            '<div class="card"><h3>الموقع</h3><p>طريق الملك فهد</p></div>'
            '<div class="card"><h3>المساحة</h3><p>15000 م2</p></div>'
            '<div class="card"><h3>التكلفة</h3><p>120 مليون</p></div>'
            '<div class="card"><h3>العائد</h3><p>18%</p></div>'
            '</div>')
        slides = [source]
        designer_agent_ids.ensure_slide_ids(slides)
        source_id = slides[0]['id']
        result, _msg = designer_chat_safety.execute_structure(
            'split_slide', {'slide_number': 1, 'parts': 2}, slides, 'قسّم',
            edit_slide=self.editor, reliability=reliability,
            carry_watermark=lambda src, out: out, progress=lambda *a, **k: None)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0]['id'], source_id)
        self.assertNotEqual(slides[1]['id'], source_id)
        self.assertEqual(slides[1].get('split_from'), source_id)

    def test_merge_keeps_first_id_and_records_both(self):
        import designer_chat_reliability as reliability
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        id1, id2 = slides[0]['id'], slides[1]['id']

        def merge_editor(html, title, instruction, index, kind, total, source):
            return html.replace('</div>', '<p>ب</p></div>'), 'تم'
        result, _msg = designer_chat_safety.execute_structure(
            'merge_slides', {'slide_numbers': [1, 2]}, slides, 'ادمج',
            edit_slide=merge_editor, reliability=reliability,
            carry_watermark=lambda src, out: out, progress=lambda *a, **k: None)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(slides), 1)
        self.assertEqual(slides[0]['id'], id1)
        self.assertEqual(slides[0].get('merged_from'), [id1, id2])

    def test_created_slide_has_a_fresh_id(self):
        import designer_chat_reliability as reliability
        slides = [slide('<p>أ</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        result, _msg = designer_chat_safety.execute_structure(
            'create_slide', {'position': 2, 'title': 'جديدة'}, slides, 'أضف',
            edit_slide=self.editor, reliability=reliability,
            carry_watermark=lambda src, out: out, progress=lambda *a, **k: None)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(slides), 2)
        ids = [s['id'] for s in slides]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(re.fullmatch(r's_[0-9a-f]{8}', slides[1]['id']))


if __name__ == '__main__':
    unittest.main()
