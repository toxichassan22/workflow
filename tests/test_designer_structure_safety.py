"""Structural edits commit only complete, explicitly targeted provider results."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import designer_chat_reliability as reliability
import designer_chat_safety as safety


def slide(body, title='Source'):
    return {'title': title, 'type': 'content', 'section_key': 'basic',
            'html': '<div class="slide">' + body + '</div>'}


class StructureSafetyTests(unittest.TestCase):
    def run_action(self, tool, params, slides, results=None, message='requested structure'):
        before = copy.deepcopy(slides)
        editor = Mock(side_effect=results or AssertionError('Unexpected provider call'))
        result, status = safety.execute_structure(
            tool, params, slides, message, edit_slide=editor, reliability=reliability,
            carry_watermark=lambda old, new: new, progress=Mock())
        return result, status, before, editor

    def assert_failed_unchanged(self, tool, params, slides, results=None):
        result, status, before, editor = self.run_action(tool, params, slides, results)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(slides, before)
        self.assertIn('لم تتغير أي شريحة', status)
        return result, editor

    def test_merge_requires_exactly_two_distinct_explicit_indexes(self):
        for params in ({}, {'slide_numbers': [1]}, {'slide_numbers': [1, 1]},
                       {'slide_numbers': [1, 2, 3]}, {'slide_numbers': [0, 2]},
                       {'slide_numbers': [1, 5]}, {'slide_numbers': [True, 2]},
                       {'slide_numbers': [1.8, 2]}, {'slide_numbers': ['bad', 2]},
                       {'slide_numbers': [1, 2], 'first_slide': 1}):
            with self.subTest(params=params):
                _, editor = self.assert_failed_unchanged('merge_slides', params,
                                                         [slide('<p>A</p>'), slide('<p>B</p>')])
                editor.assert_not_called()

    def test_merge_failure_empty_malformed_and_incomplete_do_not_delete(self):
        sources = [slide('<p>A 123</p><img src="/a.png">'), slide('<p>B 456</p><img src="/b.png">')]
        for output in ('', sources[0]['html'], '<div class="slide"><p>A 123</p>',
                       slide('<p>A 123</p><p>B 456</p><img src="/a.png">')['html'],
                       slide('<p>A 123</p><img src="/a.png"><!-- B 456 --><img src="/b.png">')['html'],
                       slide('<p>A 123</p><img src="/a.png"><p hidden>B 456</p><img src="/b.png">')['html']):
            with self.subTest(output=output):
                self.assert_failed_unchanged('merge_slides', {'slide_numbers': [1, 2]},
                                             copy.deepcopy(sources), [(output, 'done')])
        self.assert_failed_unchanged('merge_slides', {'slide_numbers': [1, 2]},
                                     sources, [RuntimeError('provider down')])

    def test_merge_passes_full_sources_and_keeps_unrelated_slides_exact(self):
        first = slide('<h1>First</h1><p>Exact first text 100.5</p><img src="/a.png">')
        second = slide('<h1>Second</h1><table><tr><td>Revenue</td><td>500</td></tr></table>'
                       '<div data-map-id="overview" style="background-image:url(/map.png)"></div>')
        merged = slide(first['html'][19:-6] + second['html'][19:-6])['html']
        workspace = [slide('<p>Before</p>'), first, slide('<p>Between</p>'), second, slide('<p>After</p>')]
        result, _, before, editor = self.run_action('merge_slides', {'slide_numbers': [4, 2]}, workspace, [(merged, 'done')])
        self.assertEqual(result['status'], 'success', result)
        self.assertIs(workspace[1], first)
        self.assertEqual([workspace[0], workspace[2], workspace[3]], [before[0], before[2], before[4]])
        self.assertIn(json.dumps(before[1], ensure_ascii=False), editor.call_args.args[2])
        self.assertIn(json.dumps(before[3], ensure_ascii=False), editor.call_args.args[2])
        self.assertEqual(workspace[1]['merged_sources'], [before[1], before[3]])

    def test_merge_checks_duplicate_occurrences_and_row_associations(self):
        sources = [slide('<p>Repeated</p><table><tr><td>A</td><td>10</td></tr></table>')['html'],
                   slide('<p>Repeated</p><table><tr><td>B</td><td>20</td></tr></table>')['html']]
        missing_duplicate = slide('<p>Repeated</p><table><tr><td>A</td><td>10</td></tr>'
                                  '<tr><td>B</td><td>20</td></tr></table>')['html']
        swapped = slide('<p>Repeated</p><p>Repeated</p><table><tr><td>A</td><td>20</td></tr>'
                        '<tr><td>B</td><td>10</td></tr></table>')['html']
        for output in (missing_duplicate, swapped):
            with self.assertRaises(safety.StructureSafetyError):
                safety.require_preserved(sources, [output], 1)

    def test_split_honors_requested_table_parts_and_preserves_metadata(self):
        rows = ''.join(f'<tr><td>Row {i}</td><td>{i * 100}</td></tr>' for i in range(9))
        source = slide('<h1>Table</h1><table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>' + rows + '</tbody></table>')
        source['content_source'] = 'financial:table'
        workspace = [slide('<p>Before</p>'), source, slide('<p>After</p>')]
        result, _, before, editor = self.run_action('split_slide', {'slide_number': 2, 'parts': 3}, workspace)
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['parts'], 3)
        self.assertEqual(len(workspace), 5)
        self.assertEqual(workspace[0], before[0])
        self.assertEqual(workspace[-1], before[-1])
        self.assertTrue(all(item['content_source'] == 'financial:table' for item in workspace[1:4]))
        editor.assert_not_called()
        safety.require_preserved([source['html']], [item['html'] for item in workspace[1:4]], 3)

    def test_split_does_not_cap_seven_parts_to_six(self):
        source = slide(''.join(f'<p>Item {i}</p>' for i in range(7)))
        result, _, _, editor = self.run_action('split_slide', {'slide_number': 1, 'parts': 7}, [source])
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['parts'], 7)
        editor.assert_not_called()

    def test_split_partial_provider_result_is_atomic(self):
        workspace = [slide('<h1>Heading</h1><section>A 123</section><section>B 456</section>')]
        part = slide('<h1>Heading</h1><section>A 123</section>')['html']
        for second in (RuntimeError('provider down'), ('', 'done'), (workspace[0]['html'], 'done')):
            with self.subTest(second=second):
                self.assert_failed_unchanged('split_slide', {'slide_number': 1, 'parts': 2},
                                             copy.deepcopy(workspace), [(part, 'done'), second])

    def test_split_complete_provider_parts_succeed(self):
        source = slide('<h1>Heading</h1><section>A 123</section><section>B 456</section><img src="/b.png">')
        a = slide('<h1>Heading</h1><section>A 123</section>')['html']
        b = slide('<h1>Heading</h1><section>B 456</section><img src="/b.png">')['html']
        workspace = [source]
        result, _, _, editor = self.run_action('split_slide', {'slide_number': 1, 'parts': 2}, workspace, [(a, 'done'), (b, 'done')])
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(editor.call_count, 2)
        self.assertEqual([item['html'] for item in workspace], [a, b])

    def test_split_missing_content_or_duplicate_parts_fail(self):
        source = slide('<section>A 123</section><section>B 456</section><img src="/b.png">')
        a = slide('<section>A 123</section>')['html']
        b = slide('<section>B 456</section>')['html']
        for outputs in ([(a, 'done'), (a, 'done')], [(a, 'done'), (b, 'done')]):
            self.assert_failed_unchanged('split_slide', {'slide_number': 1, 'parts': 2}, [copy.deepcopy(source)], outputs)

    def test_split_invalid_parts_or_missing_target_never_calls_provider(self):
        for params in ({'parts': 2}, {'slide_number': 0}, {'slide_number': True},
                       *({'slide_number': 1, 'parts': value} for value in (0, 1, 21, 100, True, 2.5, '', None))):
            with self.subTest(params=params):
                _, editor = self.assert_failed_unchanged('split_slide', params, [slide('<p>A</p><p>B</p>')])
                editor.assert_not_called()
        with self.assertRaises(safety.StructureSafetyError):
            safety.requested_parts({}, 'قسم إلى 100 شرائح', reliability.split_request_parts)

    def test_create_slot_after_and_default_append(self):
        for params, expected in (({'position': 1}, 0), ({'position': 2}, 1),
                                 ({'position': 4}, 3), ({'after': 1}, 1),
                                 ({'after': 3}, 3), ({'index': 1}, 0), ({}, 3)):
            with self.subTest(params=params):
                workspace = [slide('<p>A</p>'), slide('<p>B</p>'), slide('<p>C</p>')]
                new = slide('<p>New generated content</p>')['html']
                result, _, before, editor = self.run_action('create_slide', params, workspace, [(new, 'done')])
                self.assertEqual(result['status'], 'success', result)
                self.assertEqual(result['index'], expected)
                self.assertEqual(workspace[expected]['html'], new)
                self.assertEqual(workspace[:expected] + workspace[expected + 1:], before)
                self.assertEqual(editor.call_args.args[3], expected)

    def test_create_invalid_positions_are_not_clamped_or_defaulted(self):
        for params in ({'position': 0}, {'after': 0}, {'position': -1}, {'position': 5},
                       {'after': 4}, {'position': 'bad'}, {'position': True},
                       {'position': 1.5}, {'position': None}, {'position': 1, 'after': 1}):
            with self.subTest(params=params):
                _, editor = self.assert_failed_unchanged('create_slide', params, [slide('<p>A</p>')] * 3)
                editor.assert_not_called()

    def test_create_failure_and_multislide_output_do_not_insert(self):
        for result in (('', 'done'), (slide('<p>A</p>')['html'] * 2, 'done'), RuntimeError('offline')):
            self.assert_failed_unchanged('create_slide', {'position': 1}, [slide('<p>A</p>')], [result])
        workspace = [slide('<p>A</p>')]
        editor = Mock(side_effect=lambda html, *args: (html, 'done'))
        result, _ = safety.execute_structure('create_slide', {}, workspace, 'create', edit_slide=editor,
                                             reliability=reliability, carry_watermark=lambda a, b: b, progress=Mock())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(workspace), 1)

    def test_inventory_does_not_count_hidden_or_comment_copies(self):
        source = slide('<p>Visible exact data</p>')['html']
        for fragment in ('<!-- Visible exact data -->', '<p style="display:none">Visible exact data</p>',
                         '<script>Visible exact data</script>', '<p style="opacity:0">Visible exact data</p>'):
            with self.assertRaises(safety.StructureSafetyError):
                safety.require_preserved([source], [slide('<p>Other</p>' + fragment)['html']], 1)

    def test_unverifiable_dynamic_media_and_broken_html_fail_closed(self):
        for html in (slide('<canvas></canvas>')['html'], slide('<iframe src="/plot"></iframe>')['html'],
                     '<div class="slide-inner">Not a slide</div>', '<div class="slide"><table><tr><td>lost</div>'):
            with self.assertRaises(safety.StructureSafetyError):
                safety.validate_single_slide(html)


class StructureDispatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import auth
        import db
        cls.temp = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-structure.db')
        import app
        cls.module = app
        cls.app = app.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            cls.tenant = db.create_tenant('Structure Safety', 'structure@example.test', 'hash', 'structure-safety')
        cls.token = auth.create_token(cls.tenant, 'structure@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        import db
        db.DB_PATH = cls.previous_db_path
        cls.temp.cleanup()

    def dispatch(self, action, slides, editor):
        plan = {'response': 'تم', 'actions': [action]}
        with patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_zai_chat', return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}), \
                patch.object(self.module, '_designer_edit_slide', side_effect=editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides', side_effect=lambda slides, *args: slides), \
                patch.object(self.module.slide_engine, 'renumber_presentation_slides', side_effect=lambda slides, **kwargs: slides):
            response = self.app.test_client().post('/api/designer-chat',
                headers={'Authorization': 'Bearer ' + self.token}, json={
                    'message': 'نفذ العملية المحددة', 'slidesData': slides,
                    'projectData': {'project_name': 'Safety'}, 'slideIndex': 0})
        body = response.get_json()
        if response.status_code == 422:
            self.assertFalse(body['success'])
            self.assertEqual(body['error_code'], 'DESIGNER_ATOMIC_EDIT_FAILED')
            return body
        self.assertEqual(response.status_code, 200, body)
        return body['data']

    def test_dispatcher_does_not_delete_on_failed_merge(self):
        slides = [slide('<p>A</p>'), slide('<p>B</p>'), slide('<p>C</p>')]
        result = self.dispatch({'tool': 'merge_slides', 'params': {'slide_numbers': [1, 2]}}, slides,
                               lambda *args, **kwargs: (slides[0]['html'], 'done'))
        self.assertEqual(result['slidesData'], slides)
        self.assertEqual(result['actions'][0]['status'], 'failed')

    def test_dispatcher_create_position_one_inserts_before_first(self):
        slides = [slide('<p>A</p>'), slide('<p>B</p>')]
        html = slide('<p>New content</p>')['html']
        result = self.dispatch({'tool': 'create_slide', 'params': {'position': 1}}, slides,
                               lambda *args, **kwargs: (html, 'done'))
        self.assertEqual(result['slidesData'][0]['html'], html)
        self.assertEqual(result['slidesData'][1:], slides)

    def test_dispatcher_split_partial_provider_failure_is_unchanged(self):
        slides = [slide('<section>A</section><section>B</section>')]
        part = slide('<section>A</section>')['html']
        editor = Mock(side_effect=[(part, 'done'), RuntimeError('offline')])
        result = self.dispatch({'tool': 'split_slide', 'params': {'slide_number': 1, 'parts': 2}}, slides, editor)
        self.assertEqual(result['slidesData'], slides)
        self.assertEqual(result['actions'][0]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
