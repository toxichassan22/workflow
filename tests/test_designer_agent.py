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


class _MeasuringRender(_NoRender):
    """Render session stand-in that measures: «LONG» in the HTML clips 30px
    (an overflow the source already had), «WORSE» clips 90px."""
    available = True

    def render(self, html, screenshot=True):
        clipped = []
        if 'WORSE' in html:
            clipped = [{'tag': 'div', 'overPx': 90, 'text': 'جدول المراحل الممتد'}]
        elif 'LONG' in html:
            clipped = [{'tag': 'div', 'overPx': 30, 'text': 'جدول المراحل'}]
        report = {'ok': True, 'overflowX': False, 'overflowY': False, 'clipped': clipped,
                  'slideScroll': {'w': 1280, 'h': 720}}
        return ('data:image/png;base64,AAAA' if screenshot else None), report


# The failing slide from the field: a cell «إلى 9/2027» beside a cell «5» read
# as the pseudo-number «9/20275», so every relayout was rejected for dropping a
# value that never existed on the slide.
TIMELINE_TABLE = (
    '<h1>الجدول الزمني ومراحل التطوير</h1><table>'
    '<tr><th>المرحلة</th><th>من</th><th>إلى</th><th>المدة (شهر)</th></tr>'
    '<tr><td>التصميم</td><td>من 4/2027</td><td>إلى 9/2027</td><td>5</td></tr>'
    '<tr><td>الإنشاء</td><td>10/2027</td><td>12/2029</td><td>26</td></tr></table>')
TIMELINE_CARDS = (
    '<h1>الجدول الزمني ومراحل التطوير</h1>'
    '<div class="card"><b>التصميم</b><span>5 أشهر</span><span>من 4/2027 إلى 9/2027</span></div>'
    '<div class="card"><b>الإنشاء</b><span>26 شهر</span><span>10/2027 — 12/2029</span></div>')


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
        # Job files and failure-journal records stay inside the temp dir.
        cls.previous_uploads = app.UPLOADS_DIR
        app.UPLOADS_DIR = os.path.join(cls.temp.name, 'uploads')
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Agent', 'agent@example.test', 'hash', 'agent-slug')
            cls.platform_tenant = db.create_tenant(
                'Platform', 'platform@example.test', 'hash', 'platform-slug')
            db.get_db().execute('UPDATE tenants SET is_admin = 1 WHERE id = ?',
                                (cls.platform_tenant,))
            db.get_db().commit()
        cls.token = auth.create_token(cls.tenant, 'agent@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')
        cls.platform_token = auth.create_token(
            cls.platform_tenant, 'platform@example.test', user_id=None,
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

    def test_dropped_content_applies_with_warning_not_veto(self):
        # Owner rule: a coherent result applies even when the check finds a
        # dropped fact — the task reports a warning, the client can undo.
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
        task = body['tasks'][0]
        self.assertEqual(task['status'], 'success')
        self.assertIsNone(task.get('failureReason'))
        # The warning names the dropped value in Arabic — never the raw code.
        self.assertTrue(task.get('warnings'))
        self.assertNotIn('missing_numbers', task['warnings'][0])
        self.assertIn('120000', task['warnings'][0])
        self.assertNotIn('missing_numbers', body['response'])
        self.assertIn('120000', body['response'])
        # The edit still landed — nothing was rolled back.
        self.assertNotIn('120,000', body['slidesData'][0]['html'])

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

    def test_renumber_flattens_mangled_counter(self):
        # «73 78» / «7873 78» digit soup is still the counter, not content.
        slides = [
            slide('<p>أ</p><span data-slide-counter="1">78 — 73</span>'),
            slide('<p>خاتمة</p><div data-slide-counter="1">73 78</div>',
                  slide_type='closing'),
            slide('<p>ج</p><div style="position:absolute;bottom:34px;left:48px;">7873 78</div>',
                  slide_type='closing'),
        ]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'renumber', 'select': {'all': True}}]}
        patches = self.agent_patches(self.module, turn)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self.post({'message': 'أعد ترقيم الشرائح', 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['tasks'][0]['status'], 'success')
        self.assertIn('01 — 03', body['slidesData'][0]['html'])
        self.assertIn('02 — 03', body['slidesData'][1]['html'])
        self.assertIn('03 — 03', body['slidesData'][2]['html'])
        self.assertNotIn('73 78', body['slidesData'][1]['html'])

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
            # The confirm echoes the id-annotated deck the pending plan returned —
            # that is what the real client posts, and the id+title+hash signature
            # only matches when it does.
            confirm = self.post({'message': 'نفذ', 'slidesData': body.get('slidesData') or slides,
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

    def test_cancel_marker_written_before_run_still_stops_it(self):
        # A stop click during planning writes the marker before the run starts —
        # clearing it at task one used to swallow the cancel entirely.
        import app as app_module
        job_id = 'agentjob03'
        slides = [slide('<p>أ</p>')]
        designer_agent_ids.ensure_slide_ids(slides)
        ctx = {'job_id': job_id, 'tenant_id': self.tenant, 'slides': slides,
               'current_index': 0, 'message': 'عدل',
               'report_progress': lambda *a, **k: None}
        with self.app.test_request_context():
            app_module._write_job('.designer_chat_jobs', self.tenant, job_id, {
                'status': 'running', 'success': True, 'progress': 10,
                'payload': {'data': {}}})
        self.assertTrue(app_module._agent_job_mark_cancelled(ctx))
        tasks = [{'n': 1, 'op': 'edit', 'slides': [slides[0]['id']], 'instruction': 'عدل'}]
        def editor(*a, **k):
            raise AssertionError('worker ran despite the cancel marker')
        with patch.object(self.module, '_agent_worker_edit_slide', side_effect=editor):
            run = self.module._designer_agent_run(tasks, ctx, session=None)
        self.assertTrue(run['cancelled'])
        self.assertEqual(tasks[0]['status'], 'skipped')
        self.assertEqual(tasks[0]['failureReason'], 'cancelled')
        self.assertEqual(slides[0]['html'],
                         '<div class="slide" style="width:1280px;height:720px;"><p>أ</p></div>')

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

    def test_condensing_restructure_reports_dropped_number_to_runner(self):
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
        # The executor still flags the drop — but the splice stays in place so
        # the runner's warnable path can apply it with a warning.
        self.assertFalse(ok)
        self.assertIn('facts_not_preserved', reason)
        self.assertEqual(len(ctx['slides']), 1)

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
        # The feedback names the dropped value and the source text it lived
        # in — a raw reason code gave the worker nothing to act on.
        self.assertIn('«7500000»', calls[1])
        self.assertIn('إيراد 7,500,000 ريال', calls[1])
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

        def flaky(op, before, after, **kwargs):
            verify_calls.append(op)
            if len(verify_calls) == 1:
                return False, ['overflow:12']
            return real_verify(op, before, after, **kwargs)

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

    def test_get_project_data_tool_reads_live_draft(self):
        # The deck can come from a stale snapshot; the tool re-runs the merge so
        # the planner sees what the draft holds now — and the keys it returns
        # are written back so the worker's fact block agrees with them.
        draft = {'draft_data': {'contact_phone': '0222', 'contact_name': 'جديد',
                                'project_name': 'P'}}
        ctx = {'slides': [], 'request_project_data': {'contact_phone': '0111'},
               'presentation': {'draft_id': 'd1',
                                'project_data': {'contact_phone': '0111',
                                                 'project_name': 'P'}},
               'tenant_id': self.tenant, 'project_data': {'contact_phone': '0111'},
               'superseded_numbers': set()}
        with self.app.app_context(), \
                patch.object(self.module.db, 'get_project_draft_by_id', return_value=draft):
            text, image = self.module._agent_tool_result(
                'get_project_data', {'section': 'contact'}, ctx, None)
        self.assertIsNone(image)
        payload = json.loads(text)
        values = {f['key']: f['value'] for f in payload['fields']}
        self.assertEqual(values.get('contact_phone'), '0222')
        self.assertEqual(values.get('contact_name'), 'جديد')
        self.assertEqual(ctx['project_data'].get('contact_phone'), '0222')
        self.assertIn('0111', ctx['superseded_numbers'])

    def test_get_project_data_tool_lists_sections_when_asked_nothing(self):
        ctx = {'slides': [], 'request_project_data': {}, 'presentation': None,
               'tenant_id': self.tenant, 'project_data': {}}
        with self.app.app_context():
            text, image = self.module._agent_tool_result(
                'get_project_data', {}, ctx, None)
        self.assertIsNone(image)
        payload = json.loads(text)
        keys = [s['key'] for s in payload['sections']]
        self.assertIn('contact', keys)
        self.assertIn('basic', keys)

    # ── Retry, feedback, layout and journal ─────────────────────────────────

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

    def test_timeline_relayout_passes_and_a_real_drop_retries_with_its_context(self):
        slides = [slide(TIMELINE_TABLE, title='الجدول الزمني ومراحل التطوير')]
        turn = {'kind': 'plan', 'ops': [{'op': 'redesign', 'select': {'all': True}}]}
        feedbacks = []

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            feedbacks.append(feedback)
            cards = TIMELINE_CARDS if feedback else TIMELINE_CARDS.replace('<span>5 أشهر</span>', '')
            return slide(cards)['html'], 'تم'

        before = self.journal_files()
        body = self.run_with_worker(slides, turn, worker)
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertEqual(len(feedbacks), 2)
        self.assertEqual(feedbacks[0], '')
        # The retry names the value that really went missing and where it sat.
        self.assertIn('«5» (في: «إلى 9/2027 | 5 | الإنشاء»)', feedbacks[1])
        self.assertNotIn('20275', feedbacks[1])
        self.assertIn('5 أشهر', body['slidesData'][0]['html'])
        self.assertEqual(self.journal_files(), before)

    def test_transient_worker_failure_is_retried(self):
        slides = [slide('<p>الإيراد 120,000</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'أضف عنوانًا'}]}
        calls = []

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            calls.append(feedback)
            if len(calls) == 1:
                return None, 'provider_error:[DESIGNER-WORKER] انتهت مهلة الاتصال بالمزوّد'
            html = slide_['html']
            return html[:html.rfind('</div>')] + '<h2>عنوان</h2></div>', 'تم'

        body = self.run_with_worker(slides, turn, worker, message='أضف عنوانًا')
        self.assertEqual(len(calls), 2)
        # A timeout gives the model nothing to fix — the retry itself is the fix.
        self.assertEqual(calls[1], '')
        self.assertEqual(body['tasks'][0]['status'], 'success')

    def test_billing_failure_is_not_retried_and_stops_the_run(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}
        calls = []

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            calls.append(index)
            return None, 'provider_error:[DESIGNER-WORKER] {"message": "[402] Insufficient credits"}'

        body = self.run_with_worker(slides, turn, worker, message='عدل الكل')
        self.assertEqual(calls, [0])
        self.assertTrue(body['agent']['billingStopped'])
        self.assertEqual([t['status'] for t in body['tasks']], ['failed', 'skipped'])

    def test_dropped_figure_containing_402_is_not_a_wallet_stop(self):
        # «14020» contains «402» and the worker summary says «الرصيد»; neither
        # is an exhausted wallet, and the next task must still run.
        slides = [slide('<p>المساحة 14020 م²</p>'), slide('<p>ب</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'عدل'}]}

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            if index == 0:
                return slide('<p>المساحة</p>')['html'], 'حافظت على الرصيد النقدي'
            html = slide_['html']
            return html[:html.rfind('</div>')] + '<p>+</p></div>', 'تم'

        body = self.run_with_worker(slides, turn, worker, message='عدل الكل')
        self.assertFalse(body['agent']['billingStopped'])
        # The drift now applies with a warning — and the next task still runs.
        self.assertEqual([t['status'] for t in body['tasks']], ['success', 'success'])
        self.assertIn('14020', body['tasks'][0]['warnings'][0])
        self.assertNotIn('اشحن', body['response'])

    def test_billing_detection_reads_provider_failures_only(self):
        detect = self.module._is_billing_error_text
        self.assertFalse(detect('missing_numbers:14020'))
        self.assertFalse(detect('clipped:div:402px'))
        self.assertFalse(detect('حافظت على الرصيد النقدي'))
        self.assertTrue(detect('provider_error:[DESIGNER-WORKER] {"message": "[402] Insufficient credits"}'))
        self.assertTrue(detect('incomplete_result:provider_error:[402] insufficient credits'))

    def test_inherited_overflow_does_not_fail_an_unrelated_edit(self):
        slides = [slide('<p>LONG الإيراد 120,000</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'أضف عنوانًا'}]}
        feedbacks = []

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            feedbacks.append(feedback)
            html = slide_['html']
            return html[:html.rfind('</div>')] + '<h2>عنوان</h2></div>', 'تم'

        body = self.run_with_worker(slides, turn, worker, render=_MeasuringRender(),
                                    message='أضف عنوانًا')
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertEqual(feedbacks, [''])

    def test_new_overflow_retries_with_the_clipped_element_text(self):
        slides = [slide('<p>LONG الإيراد 120,000</p>')]
        turn = {'kind': 'plan', 'ops': [
            {'op': 'edit', 'select': {'all': True}, 'instruction': 'أضف عنوانًا'}]}
        feedbacks = []

        def worker(ctx, slide_, index, instruction, total, session=None, feedback='', style_brief='', **k):
            feedbacks.append(feedback)
            extra = '<h2>عنوان</h2>' if feedback else '<h2>WORSE عنوان</h2>'
            html = slide_['html']
            return html[:html.rfind('</div>')] + extra + '</div>', 'تم'

        body = self.run_with_worker(slides, turn, worker, render=_MeasuringRender(),
                                    message='أضف عنوانًا')
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertEqual(len(feedbacks), 2)
        self.assertIn('جدول المراحل الممتد', feedbacks[1])
        self.assertIn('90px', feedbacks[1])

    def run_real_worker(self, slides, turn, worker_html, message):
        """Real scoped worker; only the provider round-trips are faked."""
        worker_calls = []

        def provider(messages, **kwargs):
            schema = ((kwargs.get('response_format') or {}).get('json_schema') or {}).get('name')
            if schema == 'designer_worker_result':
                worker_calls.append(messages)
                return {'choices': [{'message': {'content': json.dumps(
                    {'slides': [{'title': 'x', 'html': worker_html}], 'summary': 'تم'},
                    ensure_ascii=False)}}]}
            return planner_reply(turn)

        with patch.object(self.module, 'DESIGNER_AGENT', True), \
                patch.object(self.module, '_agent_render_session', return_value=_NoRender()), \
                patch.object(self.module, 'call_openrouter_messages', side_effect=provider), \
                patch.object(self.module, '_agent_worker_finalize',
                             side_effect=lambda out, *a, **k: out), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s), \
                patch.object(self.module.slide_engine, 'renumber_presentation_slides',
                             side_effect=lambda s, **k: s):
            response = self.post({'message': message, 'slidesData': slides,
                                  'projectData': {}, 'slideIndex': 0, 'autoConfirm': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['data'], worker_calls

    def test_redesign_whose_brief_names_colors_reaches_the_model(self):
        # The brief «ألوان الهوية وخلفية بيضاء» made the composed instruction
        # read as color-only: the grammar refused it and the redesign ended as
        # color_unchanged without a single model call.
        slides = [slide('<h1>الملخص</h1><p>الإيراد 120,000</p>')]
        turn = {'kind': 'plan', 'style_brief': 'استخدم ألوان الهوية بتباين أقوى وخلفية بيضاء',
                'ops': [{'op': 'redesign', 'select': {'all': True}}]}
        redesigned = slide('<h1 style="color:#0b1f33">الملخص</h1><div class="card">الإيراد 120,000</div>')['html']
        body, worker_calls = self.run_real_worker(slides, turn, redesigned, 'أعد تصميم الشريحة')
        self.assertEqual(len(worker_calls), 1)
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertIn('class="card"', body['slidesData'][0]['html'])

    def test_plain_color_edit_with_a_brief_stays_deterministic(self):
        html = ('<div class="slide" style="width:1280px;height:720px;background:#ffffff;">'
                '<p>الإيراد 120,000</p></div>')
        slides = [{'title': 'شريحة', 'type': 'content', 'html': html}]
        turn = {'kind': 'plan', 'style_brief': 'طابع فاخر',
                'ops': [{'op': 'edit', 'select': {'all': True},
                         'instruction': 'غير لون الخلفية الى الأزرق'}]}
        body, worker_calls = self.run_real_worker(slides, turn, html, 'غير لون الخلفية الى الأزرق')
        self.assertEqual(worker_calls, [])
        self.assertEqual(body['tasks'][0]['status'], 'success', body['tasks'][0])
        self.assertIn('#0000ff', body['slidesData'][0]['html'].lower())

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

    def test_value_update_drops_authorized_numbers(self):
        # «غيّر الهاتف إلى …» retires the old figure: a superseded project value
        # or a number the request itself mandates is not a silent fact loss.
        before = '<div class="slide"><p>الهاتف 0111 والمساحة 5000</p></div>'
        after = '<div class="slide"><p>الهاتف 0222 والمساحة 5000</p></div>'
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], [after], allowed_numbers={'0111'})
        self.assertTrue(ok, reasons)
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], [after], request_text='اجعل الهاتف 0222')
        self.assertTrue(ok, reasons)

    def test_value_update_still_flags_unrelated_drops(self):
        before = '<div class="slide"><p>الهاتف 0111 والمساحة 5000 والسنة 2024</p></div>'
        after = '<div class="slide"><p>الهاتف 0222</p></div>'
        # One mandated new value excuses one drop — the other two still fail.
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], [after], request_text='اجعل الهاتف 0222')
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith('missing_numbers') for r in reasons))
        ok, reasons = designer_agent_ops.verify_task_result(
            'edit', [before], [after], allowed_numbers={'0111', '5000', '2024'})
        self.assertTrue(ok, reasons)

    def test_timeline_relayout_is_not_a_dropped_number(self):
        before = slide(TIMELINE_TABLE)['html']
        after = slide(TIMELINE_CARDS)['html']
        ok, reasons = designer_agent_ops.verify_task_result(
            'redesign', [before], [after], request_text='أعد تصميم شريحة الجدول الزمني')
        self.assertTrue(ok, reasons)
        # A genuine drop still fails — named by a value the slide really shows.
        dropped = after.replace('<span>5 أشهر</span>', '')
        ok, reasons = designer_agent_ops.verify_task_result(
            'redesign', [before], [dropped], request_text='أعد تصميم شريحة الجدول الزمني')
        self.assertFalse(ok)
        self.assertEqual(reasons, ['missing_numbers:5'])

    def test_inline_siblings_are_separate_numbers_in_the_facts_check(self):
        # «<span>9/2027</span><span>5</span>» glued to «9/20275» in the
        # restructure facts check the same way cells did in the edit check.
        import designer_chat_safety
        source = '<div class="slide"><p><span>إلى 9/2027</span><span>5</span> أشهر</p></div>'
        merged = '<div class="slide"><p>المدة 5 أشهر حتى 9/2027</p></div>'
        self.assertTrue(designer_chat_safety.require_facts_preserved([source], [merged]))

    def test_retry_policy(self):
        retryable = designer_agent_ops.is_retryable_failure
        self.assertTrue(retryable('edit', 'provider_error:timeout'))
        self.assertTrue(retryable('redesign', 'unchanged'))
        self.assertTrue(retryable('split', 'incomplete_result:empty_worker_result'))
        self.assertTrue(retryable('redesign', 'overflow:12', rejected_by_check=True))
        self.assertFalse(retryable('edit', 'table_precheck:سيفرغ الجدول'))
        self.assertFalse(retryable('edit', 'color_unchanged'))
        self.assertFalse(retryable('table_edit', 'table_unchanged', rejected_by_check=True))
        self.assertFalse(retryable('insert_map', 'map_missing'))


    def test_retry_feedback_is_actionable(self):
        before = slide(TIMELINE_TABLE)['html']
        note = designer_agent_ops.retry_feedback('missing_numbers:5,2029', [before])
        self.assertIn('«5» (في: «إلى 9/2027 | 5 | الإنشاء»)', note)
        self.assertIn('«2029»', note)
        self.assertNotIn('missing_numbers', note)
        note = designer_agent_ops.retry_feedback(
            'clipped:div:40px', [before],
            {'clipped': [{'tag': 'div', 'overPx': 40, 'text': 'جدول المراحل'}]})
        self.assertIn('جدول المراحل', note)
        self.assertIn('40px', note)
        self.assertEqual(designer_agent_ops.retry_feedback('provider_error:timeout', [before]), '')




if __name__ == '__main__':
    unittest.main()
