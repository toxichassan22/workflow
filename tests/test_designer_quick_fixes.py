import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import designer_chat_targets


def slide(inner, title='شريحة', slide_type='content'):
    return {'title': title, 'type': slide_type,
            'html': f'<div class="slide" style="width:1280px;height:720px;">{inner}</div>'}


class GreetingFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.module = app

    def free_reply(self, message, history=None):
        return self.module._designer_chat_free_reply(message, history=history)

    def test_whole_message_greeting_is_free(self):
        self.assertIsNotNone(self.free_reply('سلام'))
        self.assertIsNotNone(self.free_reply('السلام عليكم'))
        self.assertIsNotNone(self.free_reply('صباح الخير'))
        self.assertIsNotNone(self.free_reply('مرحباااا'))
        self.assertIsNotNone(self.free_reply('هلاا'))

    def test_greeting_inside_a_request_reaches_the_planner(self):
        self.assertIsNone(self.free_reply('سلام عليكم كبر عنوان الشريحة 3'))
        self.assertIsNone(self.free_reply('هلا والله لو سمحت غير لون الخلفية'))

    def test_confirmations_are_answers_not_greetings(self):
        for word in ('اه', 'تمام', 'طيب', 'ماشي', 'اوك', 'ok', 'اه نفذ', 'طيب كبر العنوان'):
            with self.subTest(word=word):
                self.assertIsNone(self.free_reply(word))

    def test_no_free_reply_while_the_designer_is_waiting_for_an_answer(self):
        history = [
            {'role': 'user', 'content': 'عدل القسم المالي'},
            {'role': 'assistant', 'content': 'هل تقصد الشرائح 5 إلى 8؟'},
        ]
        self.assertIsNone(self.free_reply('سلام', history=history))
        self.assertIsNone(self.free_reply('اه', history=history))
        # A completed turn is not a pending question: greetings stay free.
        done = history + [{'role': 'user', 'content': 'نعم'},
                          {'role': 'assistant', 'content': 'تم تطبيق التعديل المطلوب.'}]
        self.assertIsNotNone(self.free_reply('سلام', history=done))


class FailureSummaryTests(unittest.TestCase):
    def test_summary_names_failed_slides_and_reason(self):
        executed = [
            {'tool': 'edit_slides', 'status': 'failed', 'reason': 'incomplete_edit',
             'requested_indexes': [4, 8]},
        ]
        summary = designer_chat_targets.action_failure_summary(executed)
        self.assertIn('5', summary)
        self.assertIn('9', summary)
        self.assertIn('تعذر', summary)

    def test_summary_is_short_and_deduplicated(self):
        executed = [{'tool': 'edit_slides', 'status': 'failed', 'reason': 'no_verified_change'}
                    for _ in range(5)]
        summary = designer_chat_targets.action_failure_summary(executed)
        self.assertLessEqual(len(summary), 600)
        self.assertEqual(summary.count('لم يتغير'), 1)


class PartialApplyTests(unittest.TestCase):
    """A multi-slide edit that fails on one slide must keep the rest."""

    @classmethod
    def setUpClass(cls):
        import auth
        import db
        cls.temp = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-partial.db')
        import app
        cls.module = app
        cls.app = app.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Partial', 'partial@example.test', 'hash', 'partial-slug')
        cls.token = auth.create_token(cls.tenant, 'partial@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')
        # Legacy-path tests — hold the agent flag off regardless of local .env.
        cls.flag_off = patch.object(cls.module, 'DESIGNER_AGENT', False)
        cls.flag_off.start()

    @classmethod
    def tearDownClass(cls):
        import db
        cls.flag_off.stop()
        db.DB_PATH = cls.previous_db_path
        cls.temp.cleanup()

    def test_one_failed_slide_keeps_the_successful_edits(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>'), slide('<p>ج</p>')]
        plan = {'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [1, 2, 3],
                                             'instruction': 'عدل'}}]}
        changed = slide('<p>أ+</p>')['html']

        def editor(html, title, instruction, index, *args, **kwargs):
            # Slide 2 (index 1) returns unchanged html: materially_changed rejects it.
            if index == 1:
                return html, 'لم يتغير'
            return html.replace('<p>أ</p>', '<p>أ+</p>').replace('<p>ج</p>', '<p>ج+</p>'), 'تم'

        with patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_zai_chat',
                             return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}), \
                patch.object(self.module, '_designer_edit_slide', side_effect=editor), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s), \
                patch.object(self.module.slide_engine, 'renumber_presentation_slides',
                             side_effect=lambda s, **k: s):
            response = self.app.test_client().post('/api/designer-chat',
                headers={'Authorization': 'Bearer ' + self.token}, json={
                    'message': 'عدل الشرائح 1 و2 و3', 'slidesData': slides,
                    'projectData': {'project_name': 'P'}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        result_slides = body['slidesData']
        self.assertIn('أ+', result_slides[0]['html'])
        self.assertIn('<p>ب</p>', result_slides[1]['html'])
        self.assertIn('ج+', result_slides[2]['html'])
        action = body['actions'][0]
        self.assertEqual(action['status'], 'partial')
        self.assertEqual(action['failed_indexes'], [1])

    def test_all_slides_failed_is_a_failure_not_a_success(self):
        slides = [slide('<p>أ</p>'), slide('<p>ب</p>')]
        plan = {'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [1, 2],
                                             'instruction': 'عدل'}}]}
        with patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_zai_chat',
                             return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}), \
                patch.object(self.module, '_designer_edit_slide',
                             side_effect=lambda html, *a, **k: (html, 'لم يتغير')), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.app.test_client().post('/api/designer-chat',
                headers={'Authorization': 'Bearer ' + self.token}, json={
                    'message': 'عدل الشرائح 1 و2', 'slidesData': slides,
                    'projectData': {'project_name': 'P'}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['actions'][0]['status'], 'failed')
        self.assertIn('لم يتم تنفيذ', body['response'])
        self.assertEqual(body.get('failureReason'), 'incomplete_edit')


if __name__ == '__main__':
    unittest.main()
