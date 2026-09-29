import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import designer_agent_ids
import designer_agent_ops
from test_designer_agent import slide, planner_reply, _NoRender, _MeasuringRender  # noqa: F401


class AuditAgentFlowTests(unittest.TestCase):
    """Audit-regression turn tests — the same app fixture as AgentFlowTests,
    duplicated per suite convention so this file stands alone."""

    @classmethod
    def setUpClass(cls):
        import auth
        import db
        cls.temp = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-agent-audit.db')
        import app
        cls.module = app
        cls.app = app.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = app.UPLOADS_DIR
        app.UPLOADS_DIR = os.path.join(cls.temp.name, 'uploads')
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('AgentAudit', 'audit@example.test', 'hash', 'audit-slug')
            cls.platform_tenant = db.create_tenant(
                'PlatformAudit', 'platform-audit@example.test', 'hash', 'platform-audit-slug')
            db.get_db().execute('UPDATE tenants SET is_admin = 1 WHERE id = ?',
                                (cls.platform_tenant,))
            db.get_db().commit()
        cls.token = auth.create_token(cls.tenant, 'audit@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')
        cls.platform_token = auth.create_token(
            cls.platform_tenant, 'platform-audit@example.test', user_id=None,
            user_name='Platform', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        import db
        cls.module.UPLOADS_DIR = cls.previous_uploads
        db.DB_PATH = cls.previous_db_path
        cls.temp.cleanup()

    def post(self, payload, token=None):
        return self.app.test_client().post(
            '/api/designer-chat',
            headers={'Authorization': 'Bearer ' + (token or self.token)},
            json=payload)

    def agent_patches(self, module, planner_turn, editor=None):
        slides_seen = []

        def fake_worker(ctx, slide, index, instruction, total, *a, **k):
            slides_seen.append(index)
            html = slide.get('html', '')
            title = slide.get('title', '')
            if editor:
                return editor(html, title, instruction, index)
            return html[:html.rfind('</div>')] + '<p>تم التعديل</p></div>', 'تم'

        return (
            patch.object(module, 'DESIGNER_AGENT', True),
            patch.object(module, '_agent_render_session', return_value=_NoRender()),
            patch.object(module, 'call_openrouter_messages',
                         return_value=planner_reply(planner_turn)),
            patch.object(module, '_agent_worker_edit_slide', side_effect=fake_worker),
            patch.object(module.designer_chat_reliability, '_auto_heal_workspace_slides',
                         side_effect=lambda s, *a: s),
            patch.object(module.slide_engine, 'renumber_presentation_slides',
                         side_effect=lambda s, **k: s),
        )

    def run_with_worker(self, slides, turn, worker, render=None, message='أعد تصميم الشريحة'):
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session',
                             return_value=render or _NoRender()), \
                patch.object(self.module, 'call_openrouter_messages',
                             return_value=planner_reply(turn)), \
                patch.object(self.module, '_agent_worker_edit_slide', side_effect=worker), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s), \
                patch.object(self.module.slide_engine, 'renumber_presentation_slides',
                             side_effect=lambda s, **k: s):
            response = self.post({'message': message, 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['data']

    def journal_files(self):
        folder = os.path.join(self.module.UPLOADS_DIR, '.designer_agent_failures', self.tenant)
        return set(os.listdir(folder)) if os.path.isdir(folder) else set()

    # ── Audit ops: duplicate / find_replace / font / ui / unsupported ────────

    def test_duplicate_op_clones_after_the_source(self):
        slides = [slide('<p>أ</p>', title='أ'), slide('<p>ب</p>', title='ب')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'duplicate', 'select': {'positions': [1]}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'كرر الشريحة الأولى', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        out = body['slidesData']
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]['title'], 'أ')
        self.assertEqual(out[1]['title'], 'أ (نسخة)')
        self.assertEqual(out[2]['title'], 'ب')
        self.assertTrue(out[1]['id'])
        self.assertNotEqual(out[0]['id'], out[1]['id'])

    def test_find_replace_rewrites_text_nodes_only(self):
        html = ('<div class="slide" style="width:1280px;height:720px;">'
                '<p data-x="قيمة">القيمة 100</p></div>')
        slides = [{'title': 'شريحة', 'type': 'content', 'html': html}]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'find_replace', 'select': {'all': True},
             'params': {'from': 'القيمة', 'to': 'المبلغ'}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'استبدل القيمة بالمبلغ', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        out = body['slidesData'][0]['html']
        self.assertIn('المبلغ 100', out)
        self.assertIn('data-x="قيمة"', out)

    def test_font_edit_rewrites_font_family_declarations(self):
        html = ('<div class="slide" style="width:1280px;height:720px;">'
                '<p style="font-family:\'Old Font\';">الإيراد 100</p></div>')
        slides = [{'title': 'شريحة', 'type': 'content', 'html': html}]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'font_edit', 'select': {'all': True}, 'params': {'font': 'Cairo'}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'غيّر الخط إلى Cairo', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        out = body['slidesData'][0]['html']
        self.assertIn("'Cairo'", out)
        self.assertNotIn('Old Font', out)

    def test_ui_op_returns_actions_for_the_client(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'ui', 'params': {'action': 'goto'}, 'select': {'positions': [2]}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'افتح الشريحة الثانية', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertEqual(body['uiActions'], [{'action': 'goto', 'index': 1}])

    def test_unsupported_op_is_admitted_not_merged(self):
        slides = [slide('<p>أ</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'},
            {'op': 'animate_slide', 'select': {'all': True}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'عدل وحرك العناصر', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(len(body['tasks']), 1)
        self.assertEqual(body['tasks'][0]['op'], 'edit')
        self.assertTrue(body.get('planWarnings'))
        self.assertTrue(any('animate_slide' in w for w in body['planWarnings']))
        self.assertNotIn('animate', json.dumps(body['tasks'][0], ensure_ascii=False))

    def test_title_change_breaks_the_confirm_signature(self):
        slides = [slide('<p>أ</p>', title='أول'), slide('<p>ب</p>', title='ثاني')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'delete', 'select': {'positions': [2]}}]}
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages',
                             return_value=planner_reply(turn)), \
                patch.object(self.module.designer_chat_reliability,
                             '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'احذف الثانية', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        body = response.get_json()['data']
        pending = body['pendingPlan']
        renamed = body.get('slidesData') or slides
        renamed[0] = dict(renamed[0], title='تغيّر العنوان')
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module.designer_chat_reliability,
                             '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            confirm = self.post({'message': 'نفذ', 'slidesData': renamed,
                                 'projectData': {}, 'slideIndex': 0,
                                 'confirmPlan': {'id': pending['id'],
                                                 'deckSignature': pending['deckSignature'],
                                                 'ops': pending['ops']}})
        self.assertEqual(confirm.get_json()['data']['action'], 'ask')

    def test_pdf_attachment_text_reaches_the_planner(self):
        import fitz
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), 'Land Plot Alpha - 2400 sqm')
        pdf_bytes = document.tobytes()
        document.close()
        data_uri = ('data:application/pdf;base64,'
                    + __import__('base64').b64encode(pdf_bytes).decode())

        seen = {}

        def planner(messages, **kwargs):
            seen['system'] = messages[0].get('content') if messages else ''
            return planner_reply({'kind': 'reply', 'message': 'تم'})

        slides = [slide('<p>أ</p>')]
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages', side_effect=planner), \
                patch.object(self.module.designer_chat_reliability,
                             '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'اقرأ المستند ولخصه', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0,
                                  'attachedDocs': [{'name': 'plot.pdf',
                                                    'dataUri': data_uri}]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('Land Plot Alpha', seen['system'])

    def test_extra_worker_parts_are_reported(self):
        slides = [slide('<p>أ</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}
        extra = slide('<p>ب إضافية</p>')['html']

        def provider(messages, **kwargs):
            schema = ((kwargs.get('response_format') or {})
                      .get('json_schema') or {}).get('name')
            if schema == 'designer_worker_result':
                return {'choices': [{'message': {'content': json.dumps(
                    {'slides': [
                        {'title': 'x',
                         'html': slides[0]['html'].replace('</div>', '<p>+</p></div>')},
                        {'title': 'y', 'html': extra}],
                     'summary': 'تم'}, ensure_ascii=False)}}]}
            return planner_reply(turn)

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages', side_effect=provider), \
                patch.object(self.module, '_agent_worker_finalize',
                             side_effect=lambda out, *a, **k: out), \
                patch.object(self.module.designer_chat_reliability,
                             '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s), \
                patch.object(self.module.slide_engine, 'renumber_presentation_slides',
                             side_effect=lambda s, **k: s):
            response = self.post({'message': 'عدل', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        body = response.get_json()['data']
        self.assertEqual(body['agent'].get('extraWorkerParts'), 1)
        self.assertIn('شريحة إضافية', body['response'])
        self.assertEqual(len(body['slidesData']), 1)

    def test_render_unavailable_is_marked_not_silent(self):
        slides = [slide('<p>أ</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}
        body = self.run_with_worker(
            slides, turn,
            lambda ctx, s, i, ins, t, session=None, feedback='', style_brief='', **k: (
                s['html'].replace('</div>', '<p>+</p></div>'), 'تم'),
            render=_NoRender())
        self.assertEqual(body['agent'].get('render'), 'unavailable')

    def test_focus_indexes_report_touched_slides(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>'), slide('<p>ج</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'positions': [2]}, 'instruction': 'عدل'}]}
        body = self.run_with_worker(
            slides, turn,
            lambda ctx, s, i, ins, t, session=None, feedback='', style_brief='', **k: (
                s['html'].replace('</div>', '<p>+</p></div>'), 'تم'))
        self.assertEqual(body.get('focusIndexes'), [2])
        assistant = [m for m in body.get('chatHistory', []) if m.get('role') == 'assistant']
        self.assertTrue(assistant)
        self.assertEqual(assistant[-1].get('slides'), [2])


class AuditVerifyTests(unittest.TestCase):
    """Selector and preservation checks added by the audit work."""

    def test_all_except_selector(self):
        slides = [slide(f'<p>{i}</p>') for i in range(5)]
        designer_agent_ids.ensure_slide_ids(slides)
        ids = [s['id'] for s in slides]
        idx, err = designer_agent_ops.resolve_selector(
            {'all': True, 'except': [ids[1], ids[3]]}, slides)
        self.assertEqual(idx, [0, 2, 4])
        idx, err = designer_agent_ops.resolve_selector(
            {'all': True, 'except': [3]}, slides)
        self.assertEqual(idx, [0, 1, 3, 4])
        idx, err = designer_agent_ops.resolve_selector(
            {'all': True, 'except': {'ids': [ids[0]]}}, slides)
        self.assertEqual(idx, [1, 2, 3, 4])

    def test_verify_flags_dropped_media_rows_and_data_attrs(self):
        before = ('<div class="slide"><img src="/a.png"><p>الإيراد 100</p>'
                  '<table><tr><td>أ</td></tr><tr><td>ب</td></tr><tr><td>ج</td></tr></table>'
                  '<div data-chart-id="c1">x</div></div>')
        after = ('<div class="slide"><p>الإيراد 100</p>'
                 '<table><tr><td>أ</td></tr></table><div>x</div></div>')
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [after])
        self.assertFalse(ok)
        codes = {r.split(':')[0] for r in reasons}
        self.assertIn('dropped_media', codes)
        self.assertIn('dropped_rows', codes)
        self.assertIn('dropped_data_attrs', codes)

    def test_verify_exact_text_requirement(self):
        before = '<div class="slide"><p>أ</p></div>'
        after = '<div class="slide"><p>نص آخر</p></div>'
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], [after], exact_text='عنوان إلزامي')
        self.assertFalse(ok)
        self.assertIn('exact_text_missing', reasons)
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before],
            ['<div class="slide"><p>عنوان إلزامي</p></div>'], exact_text='عنوان إلزامي')
        self.assertTrue(ok)

    def test_redesign_may_replace_table_markup_but_edit_may_not(self):
        before = slide('<h1>عنوان</h1><table>'
                       '<tr><td>أ 10</td></tr><tr><td>ب 20</td></tr>'
                       '<tr><td>ج 30</td></tr></table>')['html']
        after = slide('<h1>عنوان</h1><div class="card">أ 10</div>'
                      '<div class="card">ب 20</div><div class="card">ج 30</div>')['html']
        ok, reasons = designer_agent_ops.verify_task_result('redesign', [before], [after])
        self.assertTrue(ok, reasons)
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [after])
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith('dropped_rows') for r in reasons))


class LayoutRegressionTests(unittest.TestCase):
    CLEAN = {'ok': True, 'overflowX': False, 'overflowY': False, 'clipped': [],
             'slideScroll': {'w': 1280, 'h': 720}}
    CLIPPED = dict(CLEAN, clipped=[{'tag': 'div', 'overPx': 30, 'text': 'جدول'}])

    def setUp(self):
        import generate_pdf_from_preview
        self.regressions = generate_pdf_from_preview.measure_regression_reasons

    def test_inherited_fault_is_not_a_regression(self):
        self.assertEqual(self.regressions(self.CLIPPED, self.CLIPPED), [])
        overflowing = dict(self.CLEAN, overflowY=True, slideScroll={'w': 1280, 'h': 760})
        self.assertEqual(self.regressions(overflowing, dict(overflowing)), [])

    def test_new_or_worse_fault_is_a_regression(self):
        self.assertEqual(self.regressions(self.CLEAN, self.CLIPPED), ['clipped:div:30px'])
        worse = dict(self.CLIPPED, clipped=[{'tag': 'p', 'overPx': 60, 'text': 'x'}])
        self.assertEqual(self.regressions(self.CLIPPED, worse), ['clipped:p:60px'])
        overflowing = dict(self.CLEAN, overflowY=True, slideScroll={'w': 1280, 'h': 760})
        self.assertEqual(self.regressions(self.CLEAN, overflowing), ['measured_overflow'])
        grown = dict(overflowing, slideScroll={'w': 1280, 'h': 800})
        self.assertEqual(self.regressions(overflowing, grown), ['measured_overflow'])

    def test_unknown_source_keeps_the_absolute_rule(self):
        self.assertEqual(self.regressions(None, self.CLIPPED), ['clipped:div:30px'])
        self.assertEqual(self.regressions(None, self.CLEAN), [])


class FailureReasonTextTests(unittest.TestCase):
    def test_missing_numbers_maps_to_arabic_with_values(self):
        text = designer_agent_ops.failure_reason_text('missing_numbers:7378')
        self.assertNotIn('missing_numbers', text)
        self.assertIn('7378', text)
        self.assertRegex(text, r'[؀-ۿ]')
        self.assertIn('73، 78', designer_agent_ops.failure_reason_text('missing_numbers:73,78'))

    def test_plain_codes_translate(self):
        self.assertEqual(designer_agent_ops.failure_reason_text('unchanged'),
                         'أعاد المصمم الشريحة نفسها دون تغيير قابل للتحقق.')
        self.assertEqual(designer_agent_ops.failure_reason_text('ids_not_found'),
                         'لم يُعثر على الشرائح المطلوبة في العرض الحالي.')
        self.assertNotIn('exception', designer_agent_ops.failure_reason_text('exception:ValueError'))
        self.assertTrue(designer_agent_ops.failure_reason_text('bogus_code'))

    def test_facts_and_precheck_parts(self):
        text = designer_agent_ops.failure_reason_text('facts_not_preserved:numbers:80,90')
        self.assertNotIn('facts_not_preserved', text)
        self.assertIn('80، 90', text)
        self.assertEqual(designer_agent_ops.failure_reason_text('table_precheck:سيفرغ الجدول'),
                         'سيفرغ الجدول')
        # Arabic worker notes pass through untouched.
        self.assertEqual(designer_agent_ops.failure_reason_text('لا توجد خريطة معتمدة.'),
                         'لا توجد خريطة معتمدة.')

    def test_joined_reasons_dedupe(self):
        out = designer_agent_ops.failure_reason_text('unchanged;unchanged')
        self.assertEqual(out.count('دون تغيير قابل للتحقق'), 1)

    def test_public_task_shows_display_reason(self):
        public = designer_agent_ops.public_task({
            'n': 1, 'op': 'edit', 'status': 'failed', 'failureReason': 'unchanged'})
        self.assertNotIn('unchanged', public['failureReason'])
        self.assertIn('دون تغيير', public['failureReason'])
        ok_task = designer_agent_ops.public_task({'n': 1, 'op': 'edit', 'status': 'success'})
        self.assertIsNone(ok_task['failureReason'])


if __name__ == '__main__':
    unittest.main()
