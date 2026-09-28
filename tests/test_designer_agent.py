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

    def test_failed_task_reason_is_arabic_not_a_code(self):
        slides = [slide('<p>الإيراد 120,000</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}

        def editor(html, title, instruction, index, *a, **k):
            return ('<div class="slide" style="width:1280px;height:720px;">'
                    '<p>الإيراد</p></div>', 'تم')

        patches = self.agent_patches(self.module, turn, editor=editor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'عدل الشريحة', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertNotIn('missing_numbers', body['response'])
        self.assertIn('120000', body['response'])
        self.assertNotIn('missing_numbers', body['tasks'][0]['failureReason'])
        # The machine field keeps the raw code for client logic and logs.
        self.assertIn('missing_numbers', body['failureReason'])

    def test_renumber_op_rewrites_counters(self):
        counter = '<span data-slide-counter="1" dir="ltr">07 — 03</span>'
        slides = [slide('<p>أ</p>' + counter), slide('<p>ب</p>' + counter),
                  slide('<p>ج</p>' + counter)]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'renumber', 'select': {'all': True}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'أعد ترقيم الشرائح', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['op'], 'renumber')
        self.assertEqual(body['tasks'][0]['status'], 'success')
        self.assertIn('01 — 03', body['slidesData'][0]['html'])
        self.assertIn('02 — 03', body['slidesData'][1]['html'])
        self.assertIn('03 — 03', body['slidesData'][2]['html'])

    def test_structural_plan_waits_for_confirmation(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        first_id_holder = []

        def capture_editor(ctx, slide, index, instruction, total, *a, **k):
            return slide.get('html', '') + '<p>x</p>', 'تم'

        turn = {'kind': 'plan', 'ops': [
            {'op': 'delete', 'select': {'positions': [2]}}]}
        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages',
                             return_value=planner_reply(turn)), \
                patch.object(self.module, '_agent_worker_edit_slide', side_effect=capture_editor), \
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
        ctx = {'job_id': job_id, 'tenant_id': self.tenant}
        app_module._agent_job_clear_cancel(ctx)
        with self.app.test_request_context():
            app_module._write_job('.designer_chat_jobs', self.tenant, job_id, {
                'status': 'running', 'success': True, 'progress': 40, 'payload': {'data': {}}})
        response = self.app.test_client().post(
            f'/api/designer-chat/jobs/{job_id}/cancel',
            headers={'Authorization': 'Bearer ' + self.token})
        self.assertEqual(response.status_code, 200, response.get_json())
        # Cancel is a marker file, not a job-document edit — the runner reads
        # it at the next task boundary and a checkpoint write cannot race it away.
        self.assertTrue(app_module._agent_job_cancelled(ctx))
        app_module._agent_job_clear_cancel(ctx)
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

        def editor(ctx, slide, index, instruction, total, *a, **k):
            html = slide.get('html', '')
            return html[:html.rfind('</div>')] + '<p>RESUMED</p></div>', 'تم'

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages', side_effect=planner_must_not_run), \
                patch.object(self.module, '_agent_worker_edit_slide', side_effect=editor), \
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

        def editor(ctx, slide, index, instruction, total, *a, **k):
            calls.append(index)
            html = slide.get('html', '')
            return html[:html.rfind('</div>')] + '<p>R</p></div>', 'تم'

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, '_agent_worker_edit_slide', side_effect=editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.post({'message': 'أعد المحاولة', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0,
                                  'retryTasks': retry})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(calls, [1])
        self.assertIn('R', response.get_json()['data']['slidesData'][1]['html'])

    def restructure_ctx(self, slides):
        return {'slides': slides, 'current_index': 0, 'project_data': {},
                'tenant_id': self.tenant, 'branding': {}, 'presentation_id': None,
                'creative_images': {}, 'user_image_refs': None,
                'report_progress': lambda *a, **k: None}

    def test_restructure_rejects_non_contiguous_sources(self):
        # A splice over [lo..hi] would silently delete the slides between the
        # selected ids — the executor must refuse instead of dropping them.
        slides = [slide(f'<p>S{i}</p>', title=f'S{i}') for i in range(5)]
        designer_agent_ids.ensure_slide_ids(slides)
        ctx = self.restructure_ctx(slides)
        task = {'_indexes': [1, 3], '_instruction': 'ادمج', 'op': 'restructure',
                'slides': [slides[1]['id'], slides[3]['id']], 'target_count': 1}
        with patch.object(self.module, '_agent_worker_restructure',
                          side_effect=AssertionError('worker must not run')):
            ok, reply, reason, after = self.module._agent_exec_restructure(task, ctx, None)
        self.assertFalse(ok)
        self.assertEqual(reason, 'non_contiguous_sources')
        self.assertEqual(len(ctx['slides']), 5)

    def test_condensing_restructure_passes_facts_check(self):
        header = '<div class="header"><img src="/logo.png"></div>'
        slides = [
            slide(header + '<p>نص طويل عن الإيراد</p>'
                  '<table><tr><td>الإيراد</td><td>5,000,000</td></tr></table>', title='أ'),
            slide(header + '<p>تفاصيل التمويل 35%</p>'
                  '<table><tr><td>التكلفة</td><td>2,500</td></tr></table>', title='ب'),
            slide(header + '<p>خاتمة</p>', title='ج'),
            slide('<p>خارج النطاق</p>', title='خارج'),
        ]
        designer_agent_ids.ensure_slide_ids(slides)
        ctx = self.restructure_ctx(slides)
        condensed = ('<div class="slide">' + header + '<p>ملخص الإيراد</p>'
                     '<table><tr><td>الإيراد</td><td>5,000,000</td></tr>'
                     '<tr><td>التكلفة</td><td>2,500</td></tr></table>'
                     '<p>35%</p></div>')
        produced = [{'title': 'مدمج', 'html': condensed}]
        task = {'_indexes': [0, 1, 2], '_instruction': 'قلل إلى شريحة',
                'op': 'restructure', 'slides': [s['id'] for s in slides[:3]],
                'target_count': 1, 'style_brief': ''}
        with patch.object(self.module, '_agent_worker_restructure', return_value=(produced, None)), \
                patch.object(self.module, '_agent_worker_finalize', side_effect=lambda out, *a, **k: out):
            ok, reply, reason, after = self.module._agent_exec_restructure(task, ctx, None)
        self.assertTrue(ok, reason)
        self.assertEqual(len(ctx['slides']), 2)
        self.assertEqual(ctx['slides'][1]['title'], 'خارج')

    def test_condensing_restructure_rejects_dropped_number(self):
        slides = [
            slide('<p>إيراد 7,500,000 ريال</p>', title='أ'),
            slide('<p>تفاصيل</p>', title='ب'),
        ]
        designer_agent_ids.ensure_slide_ids(slides)
        ctx = self.restructure_ctx(slides)
        produced = [{'title': 'مدمج', 'html': '<div class="slide"><p>ملخص الإيراد</p></div>'}]
        task = {'_indexes': [0, 1], '_instruction': 'قلل إلى شريحة',
                'op': 'restructure', 'slides': [s['id'] for s in slides],
                'target_count': 1, 'style_brief': ''}
        with patch.object(self.module, '_agent_worker_restructure', return_value=(produced, None)), \
                patch.object(self.module, '_agent_worker_finalize', side_effect=lambda out, *a, **k: out):
            ok, reply, reason, after = self.module._agent_exec_restructure(task, ctx, None)
        self.assertFalse(ok)
        self.assertIn('facts_not_preserved', reason)
        self.assertEqual(len(ctx['slides']), 2)

    def test_restructure_retries_once_with_drop_feedback(self):
        # A facts-check rejection must reach the worker as feedback so the next
        # attempt can restore the dropped facts instead of failing silently.
        slides = [
            slide('<p>إيراد 7,500,000 ريال</p>', title='أ'),
            slide('<p>تفاصيل التمويل</p>', title='ب'),
            slide('<p>خارج النطاق</p>', title='خارج'),
        ]
        designer_agent_ids.ensure_slide_ids(slides)
        turn = {'kind': 'plan', 'ops': [
            {'op': 'restructure', 'select': {'ids': [s['id'] for s in slides[:2]]},
             'instruction': 'ادمج في شريحة', 'target_count': 1}]}
        good = '<div class="slide"><p>إيراد 7,500,000 ريال — تفاصيل التمويل</p></div>'
        calls = []

        def worker(ctx, sources, target, instruction, feedback=''):
            calls.append(feedback)
            if len(calls) == 1:
                return [{'title': 'x', 'html': '<div class="slide"><p>ملخص</p></div>'}], None
            return [{'title': 'x', 'html': good}], None

        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                patch.object(self.module, '_agent_worker_restructure', side_effect=worker), \
                patch.object(self.module, '_agent_worker_finalize',
                             side_effect=lambda out, *a, **k: out):
            response = self.post({'message': 'ادمج الشريحتين', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(len(calls), 2)
        self.assertIn('facts_not_preserved', calls[1])
        self.assertEqual(body['tasks'][0]['status'], 'success')
        self.assertIn('7,500,000', body['slidesData'][0]['html'])

    def test_verify_failure_rolls_back_and_retries_from_original_slides(self):
        slides = [
            slide('<p>إيراد 7,500,000 ريال</p>', title='أ'),
            slide('<p>تفاصيل التمويل</p>', title='ب'),
            slide('<p>خارج النطاق</p>', title='خارج'),
        ]
        designer_agent_ids.ensure_slide_ids(slides)
        originals = [s['html'] for s in slides]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'restructure', 'select': {'ids': [s['id'] for s in slides[:2]]},
             'instruction': 'ادمج في شريحة', 'target_count': 1}]}
        merged = '<div class="slide"><p>إيراد 7,500,000 ريال — تفاصيل التمويل</p></div>'
        worker_sources = []

        def worker(ctx, sources, target, instruction, feedback=''):
            worker_sources.append([s.get('html', '') for s in sources])
            return [{'title': 'x', 'html': merged}], None

        real_verify = designer_agent_ops.verify_task_result
        verify_calls = []

        def flaky(op, before, after):
            verify_calls.append(op)
            if len(verify_calls) == 1:
                return False, ['overflow:12']
            return real_verify(op, before, after)

        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                patch.object(self.module.designer_agent_ops, 'verify_task_result',
                             side_effect=flaky), \
                patch.object(self.module, '_agent_worker_restructure', side_effect=worker), \
                patch.object(self.module, '_agent_worker_finalize',
                             side_effect=lambda out, *a, **k: out):
            response = self.post({'message': 'ادمج الشريحتين', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        # The retry rebuilt from the original two slides, not from the
        # already-merged (rejected) deck.
        self.assertEqual(len(worker_sources), 2)
        self.assertEqual(worker_sources[1], originals[:2])
        self.assertEqual(body['tasks'][0]['status'], 'success')
        self.assertEqual(len(body['slidesData']), 2)

    def test_exhausted_verify_failure_restores_the_original_deck(self):
        slides = [
            slide('<p>إيراد 7,500,000 ريال</p>', title='أ'),
            slide('<p>تفاصيل التمويل</p>', title='ب'),
            slide('<p>خارج النطاق</p>', title='خارج'),
        ]
        designer_agent_ids.ensure_slide_ids(slides)
        originals = [s['html'] for s in slides]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'restructure', 'select': {'ids': [s['id'] for s in slides[:2]]},
             'instruction': 'ادمج في شريحة', 'target_count': 1}]}
        merged = '<div class="slide"><p>إيراد 7,500,000 ريال — تفاصيل التمويل</p></div>'

        def worker(ctx, sources, target, instruction, feedback=''):
            return [{'title': 'x', 'html': merged}], None

        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                patch.object(self.module.designer_agent_ops, 'verify_task_result',
                             return_value=(False, ['overflow:12'])), \
                patch.object(self.module, '_agent_worker_restructure', side_effect=worker), \
                patch.object(self.module, '_agent_worker_finalize',
                             side_effect=lambda out, *a, **k: out):
            response = self.post({'message': 'ادمج الشريحتين', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        # A failed task must not leave its rejected mutation in the returned deck.
        self.assertEqual(body['tasks'][0]['status'], 'failed')
        self.assertEqual([s['html'] for s in body['slidesData']], originals)


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

    def test_counter_chrome_is_not_a_preserved_fact(self):
        before = ('<div class="slide"><p>محتوى</p>'
                  '<footer data-slide-footer="1"><span data-slide-counter="1" dir="ltr">03 — 12</span></footer></div>')
        after = ('<div class="slide"><p>محتوى محدث</p>'
                 '<footer data-slide-footer="1"><span data-slide-counter="1" dir="ltr">05 — 12</span></footer></div>')
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [after])
        self.assertTrue(ok, reasons)

    def test_counter_drop_still_detects_content_numbers(self):
        before = ('<div class="slide"><p>الإيراد 4,500</p>'
                  '<footer data-slide-footer="1"><span data-slide-counter="1" dir="ltr">03 — 12</span></footer></div>')
        after = ('<div class="slide"><p>الإيراد</p>'
                 '<footer data-slide-footer="1"><span data-slide-counter="1" dir="ltr">03 — 12</span></footer></div>')
        ok, reasons = designer_agent_ops.verify_task_result('edit', [before], [after])
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith('missing_numbers') for r in reasons))


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
