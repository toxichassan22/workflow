import unittest

import designer_agent_ids
import designer_agent_plan as agent_plan
import designer_numbers


def mk_slides(count, start=1):
    slides = [{'title': f'شريحة {i}', 'type': 'content', 'section_key': f'sec{(i % 3) + 1}',
               'html': f'<div class="slide"><p>محتوى {i} — الرقم {i * 10}</p></div>'}
              for i in range(start, start + count)]
    designer_agent_ids.ensure_slide_ids(slides)
    return slides


class OutlineTests(unittest.TestCase):
    def test_outline_lists_every_slide_with_id_and_position(self):
        slides = mk_slides(3)
        outline = agent_plan.build_outline(slides)
        self.assertEqual([r['n'] for r in outline], [1, 2, 3])
        self.assertEqual([r['id'] for r in outline], [s['id'] for s in slides])
        self.assertIn('شريحة 2', outline[1]['title'])

    def test_density_reports_per_id(self):
        slides = mk_slides(2)
        slides[0]['html'] = '<div class="slide"><table>' + '<tr><td>x</td></tr>' * 30 + '</table></div>'
        density = agent_plan.density(slides)
        self.assertGreater(density[slides[0]['id']]['rows'], 20)
        self.assertGreater(density[slides[0]['id']]['score'], density[slides[1]['id']]['score'])
        self.assertEqual(set(density.keys()), {s['id'] for s in slides})


class ExpandPlanTests(unittest.TestCase):
    def test_range_selector_expands_to_ids(self):
        slides = mk_slides(120)
        plan = {'kind': 'plan', 'ops': [{
            'op': 'redesign',
            'select': {'range': [slides[49]['id'], slides[99]['id']]},  # «الشرائح 50 إلى 100»
            'instruction': 'أعد التصميم'}]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        self.assertFalse(errors)
        self.assertEqual(len(tasks), 51)
        self.assertTrue(all(t['op'] == 'redesign' and t['engine'] == 'worker' for t in tasks))
        self.assertEqual(tasks[0]['slides'], [slides[49]['id']])
        self.assertEqual(tasks[0]['positions_at_request'], [50])
        self.assertEqual(tasks[-1]['positions_at_request'], [100])

    def test_positions_survive_a_later_renumber(self):
        """Slides 51/59/70 redesigned, then two slides inserted before 70: the
        task still names the same ids even though 70 now sits at position 72
        and the planned range end reads 103 instead of 100."""
        slides = mk_slides(120)
        plan = {'kind': 'plan', 'ops': [{
            'op': 'redesign',
            'select': {'ids': [slides[50]['id'], slides[58]['id'], slides[69]['id']]},
            'instruction': 'أعد التصميم'}]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        self.assertFalse(errors)
        wanted = {slides[50]['id'], slides[58]['id'], slides[69]['id']}
        self.assertEqual({t['slides'][0] for t in tasks}, wanted)
        self.assertEqual(sorted(t['positions_at_request'][0] for t in tasks), [51, 59, 70])
        # Mutate the deck: two creates push former-70 to 72 and the 50-100
        # range to 50-103. The tasks resolve by id, not position.
        slides.insert(0, {'id': 's_new00001', 'title': 'x', 'html': '<div class="slide"></div>'})
        slides.insert(1, {'id': 's_new00002', 'title': 'x', 'html': '<div class="slide"></div>'})
        index = designer_agent_ids.index_by_id(slides)
        for task in tasks:
            self.assertIn(task['slides'][0], index)
        self.assertEqual(index[slides[71]['id']], 71)  # old position-70 slide now at 72

    def test_stronger_op_absorbs_weaker_on_same_slide(self):
        slides = mk_slides(5)
        plan = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'ids': [slides[1]['id']]}, 'instruction': 'غيّر الخط'},
            {'op': 'restructure', 'select': {'ids': [slides[1]['id'], slides[2]['id'], slides[3]['id']]},
             'target_count': 2, 'instruction': 'أعد الهيكلة'},
        ]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        self.assertFalse(errors)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['op'], 'restructure')
        self.assertEqual(set(tasks[0]['slides']), {slides[1]['id'], slides[2]['id'], slides[3]['id']})
        self.assertEqual(tasks[0]['target_count'], 2)
        self.assertIn('غيّر الخط', tasks[0]['instruction'])

    def test_section_selector_picks_member_slides(self):
        slides = mk_slides(9)
        plan = {'kind': 'plan', 'ops': [{'op': 'edit', 'select': {'section': 'sec2'},
                                         'instruction': 'وحّد الألوان'}]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        self.assertFalse(errors)
        got = {t['slides'][0] for t in tasks}
        self.assertEqual(got, {s['id'] for s in slides if s['section_key'] == 'sec2'})

    def test_all_and_entire_presentation(self):
        slides = mk_slides(4)
        tasks, errors = agent_plan.expand_plan(
            {'ops': [{'op': 'redesign', 'select': {'all': True}, 'instruction': 'x'}]}, slides)
        self.assertFalse(errors)
        self.assertEqual(len(tasks), 4)

    def test_missing_ids_reported_not_crashing(self):
        slides = mk_slides(3)
        plan = {'ops': [
            {'op': 'edit', 'select': {'ids': [slides[0]['id'], 's_missing']}, 'instruction': 'x'},
            {'op': 'redesign', 'select': {'range': ['s_ghost', slides[2]['id']]}, 'instruction': 'y'},
        ]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        missing = [e for e in errors if e['error'] == 'unknown_ids']
        self.assertEqual(len(missing), 2)
        self.assertIn('s_missing', missing[0]['ids'])
        # Known ids still produce tasks.
        self.assertEqual([t['slides'][0] for t in tasks if t.get('slides')], [slides[0]['id']])

    def test_code_ops_stay_grouped_and_keep_params(self):
        slides = mk_slides(6)
        plan = {'ops': [{'op': 'table_edit', 'select': {'ids': [slides[1]['id'], slides[3]['id']]},
                         'instruction': 'احذف عمود السعر', 'params': {'column': 'السعر'}}]}
        tasks, errors = agent_plan.expand_plan(plan, slides)
        self.assertFalse(errors)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['engine'], 'code')
        self.assertEqual(tasks[0]['slides'], [slides[1]['id'], slides[3]['id']])
        self.assertEqual(tasks[0]['params'], {'column': 'السعر'})

    def test_delete_is_per_slide_code_task(self):
        slides = mk_slides(3)
        tasks, errors = agent_plan.expand_plan(
            {'ops': [{'op': 'delete', 'select': {'ids': [slides[0]['id'], slides[1]['id']]}}]},
            slides)
        self.assertFalse(errors)
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t['engine'] == 'code' and t['op'] == 'delete' for t in tasks))


class NumberExtractionTests(unittest.TestCase):
    def test_numbers_normalized_and_counted(self):
        html = '<div class="slide"><p>المساحة ١٢٣٤٫٥٦ م2</p><p>السعر 120,000</p></div>'
        counts = agent_plan.extract_visible_numbers(html)
        self.assertIn('1234.56', counts)
        self.assertIn('120000', counts)

    def test_missing_numbers_reports_dropped_values(self):
        source = ['<div class="slide"><p>109 م</p><p>98 م</p><p>80.3 م</p></div>']
        result = ['<div class="slide"><p>109 م</p><p>98 م</p></div>']
        self.assertEqual(agent_plan.missing_numbers(source, result), ['80.3'])
        self.assertEqual(agent_plan.missing_numbers(source, source), [])

    def test_script_numbers_are_not_visible(self):
        html = '<div class="slide"><p>5</p><script>var x = 9999;</script></div>'
        counts = agent_plan.extract_visible_numbers(html)
        self.assertIn('5', counts)
        self.assertNotIn('9999', counts)

    # A cell «إلى 9/2027» followed by a cell «5» used to read as «9/20275»:
    # a pseudo-number that vanished on any relayout and failed the task for a
    # value that never existed on the slide.
    TIMELINE_TABLE = (
        '<div class="slide"><table>'
        '<tr><th>المرحلة</th><th>من</th><th>إلى</th><th>المدة (شهر)</th></tr>'
        '<tr><td>التصميم</td><td>من 4/2027</td><td>إلى 9/2027</td><td>5</td></tr>'
        '<tr><td>الإنشاء</td><td>10/2027</td><td>12/2029</td><td>26</td></tr>'
        '</table><p>6 1,200 7,200</p></div>')
    TIMELINE_CARDS = (
        '<div class="slide">'
        '<div class="card"><b>التصميم</b><span>5 أشهر</span><span>من 4/2027 إلى 9/2027</span></div>'
        '<div class="card"><b>الإنشاء</b><span>26 شهر</span><span>10/2027 — 12/2029</span></div>'
        '<p>6 | 1,200 | 7,200</p></div>')

    def test_neighbouring_cells_never_glue_into_one_number(self):
        counts = agent_plan.extract_visible_numbers(self.TIMELINE_TABLE)
        for pseudo in ('9/20275', '20275', '10/202712/202926', '612007200'):
            self.assertNotIn(pseudo, counts)
        self.assertEqual(counts['2027'], 3)
        for atom in ('4', '9', '5', '10', '12', '2029', '26', '6', '1200', '7200'):
            self.assertIn(atom, counts)

    def test_table_to_cards_relayout_drops_nothing(self):
        self.assertEqual(agent_plan.missing_numbers([self.TIMELINE_TABLE], [self.TIMELINE_CARDS]), [])
        dropped = self.TIMELINE_CARDS.replace('<span>5 أشهر</span>', '')
        self.assertEqual(agent_plan.missing_numbers([self.TIMELINE_TABLE], [dropped]), ['5'])

    def test_atoms_normalize_separators_padding_and_units(self):
        atoms = designer_numbers.number_atoms
        self.assertEqual(atoms('٥٬٠٠٠٬٠٠٠'), atoms('5,000,000'))
        self.assertEqual(atoms('١٢٣٤٫٥٠'), ['1234.5'])
        self.assertEqual(atoms('27/09/2026'), ['27', '9', '2026'])
        self.assertEqual(atoms('المرحلة 01'), atoms('المرحلة 1'))
        # Padding on a long run is part of the value: phones keep their zero.
        self.assertEqual(atoms('0551234567'), ['0551234567'])
        # «م2» and «م²» are the same unit, not a dropped «2».
        self.assertEqual(atoms('20,275 م2'), atoms('20,275 م²'))
        self.assertEqual(atoms('71–79'), ['71', '79'])

    def test_atom_contexts_show_where_a_bare_cell_sat(self):
        nodes = agent_plan.visible_text_nodes(self.TIMELINE_TABLE)
        pairs = dict(designer_numbers.atom_contexts(nodes, ['5', '7200', '404']))
        self.assertEqual(pairs['5'], 'إلى 9/2027 | 5 | الإنشاء')
        self.assertIn('7,200', pairs['7200'])
        self.assertEqual(pairs['404'], '')


if __name__ == '__main__':
    unittest.main()
