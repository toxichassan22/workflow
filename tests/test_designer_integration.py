"""Local edits preserve all non-target markup and current project facts."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import auth
import db


class DesignerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-integration.db')
        import app
        cls.module = app
        app.app.config.update(TESTING=True)
        with app.app.app_context():
            cls.tenant = db.create_tenant('Designer', 'designer@example.test', 'hash', 'designer')
        cls.token = auth.create_token(cls.tenant, 'designer@example.test', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def call(self, actions, slides, message, project=None, **kwargs):
        plan = {'response': 'planned', 'actions': actions}
        with patch.object(self.module, 'call_zai_chat', return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}) as model:
            response = self.module.app.test_client().post('/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': message, 'slidesData': slides, 'projectData': project or {'project_name': 'Test'}, **kwargs})
        return response, model

    @staticmethod
    def slides():
        return [{'title': 'Untouched', 'type': 'section_divider', 'section_key': 'financial',
                 'html': '<div class="slide" style="background:#abcdef"><p>1234.56</p></div>'},
                {'title': 'Table', 'type': 'content', 'html': '<div class="slide"><h1 style="color:#112233">Title</h1><table><thead><tr><th>البند</th><th>السعر</th></tr></thead><tbody><tr><td>A</td><td>1234.56</td></tr><tr><td>B</td><td>12.34%</td></tr></tbody></table><p>Keep</p></div>'}]

    def test_table_column_edit_is_surgical_and_does_not_call_editor_model(self):
        slides = self.slides()
        response, model = self.call([{'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [2], 'instruction': 'احذف عمود السعر'}}], slides, 'احذف عمود السعر في الشريحة 2')
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()['data']['slidesData']
        self.assertEqual(result[0], slides[0])
        expected = slides[1]['html'].replace('<th>السعر</th>', '').replace('<td>1234.56</td>', '').replace('<td>12.34%</td>', '')
        self.assertEqual(result[1]['html'], expected)
        self.assertEqual(model.call_count, 1)

    def test_color_edit_preserves_text_numbers_and_other_slide(self):
        slides = self.slides()
        response, model = self.call([{'tool': 'edit_slides', 'params': {'indexes': [2], 'instruction': 'استبدل اللون #112233 باللون #445566'}}], slides, 'استبدل اللون #112233 باللون #445566 في الشريحة 2')
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()['data']['slidesData']
        self.assertEqual(result[0], slides[0])
        self.assertEqual(result[1]['html'], slides[1]['html'].replace('#112233', '#445566'))
        self.assertEqual(model.call_count, 1)

    def test_invalid_target_and_partial_edit_apply_nothing(self):
        slides = self.slides()
        response, _ = self.call([{'tool': 'edit_slides', 'params': {'indexes': [999], 'instruction': 'احذف الصف 1'}}], slides, 'احذف الصف 1', **{'indexes': [999]})
        self.assertEqual(response.status_code, 422)
        response, _ = self.call([{'tool': 'edit_slides', 'params': {'target': 'all', 'instruction': 'احذف الصف 1'}}], slides, 'احذف الصف 1 من كل الشرائح')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()['slidesData'], slides)

    def test_planner_and_editor_get_full_deck_and_project(self):
        slides = self.slides()
        project = {'project_name': 'Test', 'custom': 'x' * 7000 + 'TAIL_FACT',
                   'nearby_landmarks_data': json.dumps([{'custom': 'LANDMARK_EXTENSION'}])}
        prompts = []
        def provider(prompt, instruction, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                content = {'actions': [{'tool': 'edit_slides', 'params': {'indexes': [2], 'instruction': 'أضف النص المطلوب'}}]}
            else:
                content = {'html': slides[1]['html'].replace('<p>Keep</p>', '<p>Keep</p><p>TAIL_FACT</p>'), 'response': 'تمت الإضافة'}
            return {'choices': [{'message': {'content': json.dumps(content)}}]}
        with patch.object(self.module, 'call_zai_chat', side_effect=provider), patch('generate_pdf_from_preview.render_slide_to_image_base64', return_value=None):
            response = self.module.app.test_client().post('/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token}, json={
                'message': 'أضف النص للشريحة 2', 'slidesData': slides, 'projectData': project})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertGreaterEqual(len(prompts), 2)
        for prompt in prompts:
            for value in ['TAIL_FACT', 'LANDMARK_EXTENSION', '#abcdef', 'Untouched', '1234.56']:
                self.assertIn(value, prompt)
        self.assertEqual(response.get_json()['data']['slidesData'][0], slides[0])

    def test_operational_merge_preserves_urls_and_explicit_clears(self):
        with patch.object(db, 'get_project_draft_by_id', return_value={'draft_data': {'image': '/uploads/a.png', 'custom': {'old': True}, 'logo': '/uploads/b.png'}}):
            result = self.module._designer_project_data_for_request({'custom': {}, 'logo': ''}, {'draft_id': 'draft'}, self.tenant)
        self.assertEqual(result['image'], '/uploads/a.png')
        self.assertEqual(result['custom'], {})
        self.assertEqual(result['logo'], '')

    def test_save_numbering_does_not_rebuild_edited_content(self):
        slides = self.slides()
        slides[1]['_designer_keep_html'] = True
        with self.module.app.app_context():
            result = self.module.slide_engine.renumber_presentation_slides(slides, branding={}, project_data={})
        self.assertEqual(result[1]['html'], slides[1]['html'])
        result = self.module.slide_engine.renumber_presentation_slides(slides, branding={}, project_data={}, preserve_html=True)
        self.assertEqual([s['html'] for s in result], [s['html'] for s in slides])


if __name__ == '__main__':
    unittest.main()
