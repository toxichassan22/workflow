import json
import os
import tempfile
import unittest
from unittest.mock import patch

import designer_agent_ids
import designer_agent_ops
import designer_agent_plan


def slide(inner, title='شريحة', slide_type='content'):
    return {'title': title, 'type': slide_type,
            'html': f'<div class="slide" style="width:1280px;height:720px;">{inner}</div>'}


def planner_reply(turn):
    return {'choices': [{'message': {'content': json.dumps(turn, ensure_ascii=False)}}]}


class _NoRender:
    """Render session stand-in: measurement disabled, planner render tool errors."""
    available = False

    def render(self, html, screenshot=True):
        return None, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AgentFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import auth
        import db
        cls.temp = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-agent.db')
        import app
        cls.module = app
        cls.app = app.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Agent', 'agent@example.test', 'hash', 'agent-slug')
        cls.token = auth.create_token(cls.tenant, 'agent@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        import db
        db.DB_PATH = cls.previous_db_path
        cls.temp.cleanup()

    def post(self, payload, token=None):
        return self.app.test_client().post(
            '/api/designer-chat',
            headers={'Authorization': 'Bearer ' + (token or self.token)},
            json=payload)

    def agent_patches(self, module, planner_turn, editor=None):
        slides_seen = []

        def fake_editor(html, title, instruction, index, *a, **k):
            slides_seen.append(index)
            if editor:
                return editor(html, title, instruction, index, *a, **k)
            return html[:html.rfind('</div>')] + '<p>تم التعديل</p></div>', 'تم'

        return (
            patch.object(module, 'DESIGNER_AGENT', True),
            patch.object(module, '_agent_render_session', return_value=_NoRender()),
            patch.object(module, 'call_openrouter_messages',
                         return_value=planner_reply(planner_turn)),
            patch.object(module, '_designer_edit_slide', side_effect=fake_editor),
            patch.object(module.designer_chat_reliability, '_auto_heal_workspace_slides',
                         side_effect=lambda s, *a: s),
            patch.object(module.slide_engine, 'renumber_presentation_slides',
                         side_effect=lambda s, **k: s),
        )

    def test_flag_off_keeps_legacy_path(self):
        slides = [slide('<p>أ</p>')]
        plan = {'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'current', 'instruction': 'x'}}]}
        with patch.object(self.module, 'DESIGNER_AGENT', False), \
                patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_zai_chat',
                             return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}), \
                patch.object(self.module, '_designer_edit_slide',
                             side_effect=lambda html, *a, **k: (html + 'x', 'تم')), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'عدل الشريحة', 'slidesData': slides,
                                  'projectData': {'project_name': 'P'}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn('agent', response.get_json()['data'])

    def test_reply_turn_never_touches_the_deck(self):
        slides = [slide('<p>أ</p>')]
        patches = self.agent_patches(self.module, {'kind': 'reply', 'message': 'أهلاً'})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'ما الذي تستطيع فعله؟', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'chat_only')
        self.assertEqual(body['response'], 'أهلاً')
        self.assertNotIn('slidesData', body)

    def test_plan_runs_tasks_and_returns_checklist(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'حسّن النص'}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'حسّن كل الشرائح', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'workspace_update')
        self.assertEqual(body['agent']['mode'], 'runner')
        self.assertEqual(body['agent']['done'], 2)
        self.assertEqual(len(body['tasks']), 2)
        self.assertTrue(all(t['status'] == 'success' for t in body['tasks']))
        self.assertIn('تم التعديل', body['slidesData'][0]['html'])
        self.assertIn('تم التعديل', body['slidesData'][1]['html'])

    def test_failed_task_preserves_successful_work(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>'), slide('<p>ج</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}

        def editor(html, title, instruction, index, *a, **k):
            if index == 1:
                return html, 'لم يتغير'   # unchanged → verification fails both attempts
            return html[:html.rfind('</div>')] + '<p>+</p></div>', 'تم'

        patches = self.agent_patches(self.module, turn, editor=editor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'عدل الكل', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['agent']['done'], 2)
        self.assertEqual(body['agent']['failed'], 1)
        statuses = {t['n']: t['status'] for t in body['tasks']}
        self.assertEqual(statuses[2], 'failed')
        self.assertIn('failureReason', body)
        self.assertIn('<p>+</p>', body['slidesData'][0]['html'])
        self.assertIn('<p>ب</p>', body['slidesData'][1]['html'])
        self.assertIn('<p>+</p>', body['slidesData'][2]['html'])

    def test_structural_plan_waits_for_confirmation(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        first_id_holder = []

        def capture_editor(html, title, instruction, index, *a, **k):
            return html + '<p>x</p>', 'تم'

        turn = {'kind': 'plan', 'ops': [
            {'op': 'delete', 'select': {'positions': [2]}}]}
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages',
                             return_value=planner_reply(turn)), \
                patch.object(self.module, '_designer_edit_slide', side_effect=capture_editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'احذف الشريحة الثانية', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'plan_pending')
        self.assertEqual(body['pendingPlan']['tasks'][0]['op'], 'delete')
        pending = body['pendingPlan']
        # The deck is untouched until the user confirms.
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            confirm = self.post({'message': 'نفذ', 'slidesData': slides,
                                 'projectData': {}, 'slideIndex': 0,
                                 'confirmPlan': {'id': pending['id'],
                                                 'deckSignature': pending['deckSignature'],
                                                 'style_brief': '',
                                                 'ops': pending['ops']}})
        cbody = confirm.get_json()['data']
        self.assertEqual(cbody['action'], 'workspace_update')
        self.assertEqual(len(cbody['slidesData']), 1)

    def test_stale_deck_rejects_confirmation(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        turn = {'kind': 'plan', 'ops': [{'op': 'delete', 'select': {'positions': [2]}}]}
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages',
                             return_value=planner_reply(turn)), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'احذف الثانية', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        pending = response.get_json()['data']['pendingPlan']
        different = [slide('<p>أ</p>'), slide('<p>ب</p>'), slide('<p>ج</p>')]
        designer_agent_ids.ensure_slide_ids(different)
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()):
            confirm = self.post({'message': 'نفذ', 'slidesData': different,
                                 'projectData': {}, 'slideIndex': 0,
                                 'confirmPlan': {'id': pending['id'],
                                                 'deckSignature': pending['deckSignature'],
                                                 'ops': pending['ops']}})
        body = confirm.get_json()['data']
        self.assertEqual(body['action'], 'ask')
        self.assertNotIn('slidesData', body)

    def test_cancel_endpoint_marks_job(self):
        import app as app_module
        job_id = 'agentjob01'
        with self.app.test_request_context():
            app_module._write_job('.designer_chat_jobs', self.tenant, job_id, {
                'status': 'running', 'success': True, 'progress': 40, 'payload': {'data': {}}})
        response = self.app.test_client().post(
            f'/api/designer-chat/jobs/{job_id}/cancel',
            headers={'Authorization': 'Bearer ' + self.token})
        self.assertEqual(response.status_code, 200, response.get_json())
        job = app_module._read_job('.designer_chat_jobs', self.tenant, job_id)
        self.assertTrue(job['cancelRequested'])
        # A finished job cannot be cancelled.
        with self.app.test_request_context():
            app_module._write_job('.designer_chat_jobs', self.tenant, job_id,
                                  {'status': 'completed'})
        response = self.app.test_client().post(
            f'/api/designer-chat/jobs/{job_id}/cancel',
            headers={'Authorization': 'Bearer ' + self.token})
        self.assertEqual(response.status_code, 409)

    def test_job_resume_skips_planner(self):
        """A job carrying agentState resumes pending tasks without re-planning."""
        import app as app_module
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        tasks = [
            {'n': 1, 'op': 'edit', 'slides': [slides[0]['id']], 'status': 'success',
             'instruction': 'x'},
            {'n': 2, 'op': 'edit', 'slides': [slides[1]['id']], 'status': 'pending',
             'instruction': 'عدل'},
        ]
        job_id = 'agentjob02'
        with self.app.test_request_context():
            app_module._write_job('.designer_chat_jobs', self.tenant, job_id, {
                'status': 'running', 'success': True, 'progress': 50,
                'payload': {'data': {}},
                'agentState': {'planId': 'p1', 'tasks': tasks, 'slides': slides}})

        def planner_must_not_run(*a, **k):
            raise AssertionError('planner was called during resume')

        def editor(html, title, instruction, index, *a, **k):
            return html[:html.rfind('</div>')] + '<p>RESUMED</p></div>', 'تم'

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages', side_effect=planner_must_not_run), \
                patch.object(self.module, '_designer_edit_slide', side_effect=editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'عدل', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0,
                                  '_job_id': job_id})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertIn('RESUMED', body['slidesData'][1]['html'])
        self.assertEqual(body['agent']['done'], 2)

    def test_retry_tasks_runs_only_those(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        retry = [{'n': 1, 'op': 'edit', 'slides': [slides[1]['id']],
                  'status': 'failed', 'instruction': 'عدل'}]

        calls = []

        def editor(html, title, instruction, index, *a, **k):
            calls.append(index)
            return html[:html.rfind('</div>')] + '<p>R</p></div>', 'تم'

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, '_designer_edit_slide', side_effect=editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'أعد المحاولة', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0,
                                  'retryTasks': retry})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(calls, [1])
        self.assertIn('R', response.get_json()['data']['slidesData'][1]['html'])


class SelectorAndVerifyTests(unittest.TestCase):
    def test_selector_forms(self):
        slides = [slide(f'<p>{i}</p>') for i in range(5)]
        designer_agent_ids.ensure_slide_ids(slides)
        ids = [s['id'] for s in slides]
        idx, _ = designer_agent_ops.resolve_selector({'ids': [ids[1], ids[3]]}, slides)
        self.assertEqual(idx, [1, 3])
        idx, _ = designer_agent_ops.resolve_selector({'range': [ids[1], ids[3]]}, slides)
        self.assertEqual(idx, [1, 2, 3])
        idx, _ = designer_agent_ops.resolve_selector({'all': True}, slides)
        self.assertEqual(idx, [0, 1, 2, 3, 4])
        idx, _ = designer_agent_ops.resolve_selector({'current': True}, slides, current_index=2)
        self.assertEqual(idx, [2])
        idx, err = designer_agent_ops.resolve_selector({'ids': ['nope']}, slides)
        self.assertEqual(idx, [])
        self.assertTrue(err)

    def test_verify_detects_unchanged_and_missing_numbers(self):
        before = '<div class="slide"><p>الإيراد 120,000</p></div>'
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [before])
        self.assertFalse(ok)
        self.assertIn('unchanged', reasons)
        after = '<div class="slide"><p>الإيراد</p></div>'
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [after])
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith('missing_numbers') for r in reasons))
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], ['<div class="slide"><p>الإيراد 120,000 محدث</p></div>'])
        self.assertTrue(ok, reasons)

    def test_invalid_html_fails_closed(self):
        ok, reasons = designer_agent_ops.verify_task_result('edit', ['<div class="slide">x</div>'], [''])
        self.assertFalse(ok)
        self.assertIn('empty_result', reasons)


if __name__ == '__main__':
    unittest.main()
