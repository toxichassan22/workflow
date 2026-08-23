"""What the company admin agent can actually do, and what it must refuse.

The suite uses a temporary SQLite database and never calls an AI provider: the model reply is always
patched, so every assertion is about this repository's own behaviour.
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db
from design_templates import build_design_rules


def _reply_with(actions, text='تم'):
    blocks = '\n'.join('```action\n' + json.dumps(action, ensure_ascii=False) + '\n```'
                       for action in actions)
    return {'choices': [{'message': {'content': f'{text}\n{blocks}'}}]}


class AdminAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'admin-agent.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            cls.tenant = db.create_tenant('Agent Co', 'agent@example.test', 'hash', 'agent-co')

        cls.token = auth.create_token(
            cls.tenant, 'agent@example.test', user_id=None, user_name='Agent Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _run(self, tool, **params):
        with self.app.app_context():
            return self.application_module._execute_agent_action(
                self.tenant, {'tool': tool, 'params': params}
            )

    # ── The company team library ──────────────────────────────────────────

    def test_agent_manages_the_team_library(self):
        """The database functions and REST routes existed; the agent had no tool for any of them."""
        added = self._run('add_team_entity', name='مكتب الرياض للاستشارات',
                          role='الاستشاري الهندسي', brief='مكتب تصميم', experience_years='12')
        self.assertEqual(added['status'], 'success', added.get('message'))

        listed = self._run('list_team')
        names = [item['name'] for item in listed['data']]
        self.assertIn('مكتب الرياض للاستشارات', names)

        updated = self._run('update_team_entity', name='مكتب الرياض للاستشارات',
                            updates={'role': 'المقاول الرئيسي', 'experienceYears': '15'})
        self.assertEqual(updated['status'], 'success', updated.get('message'))
        with self.app.app_context():
            entity = next(item for item in db.get_team_entities(self.tenant)
                          if item['name'] == 'مكتب الرياض للاستشارات')
        self.assertEqual(entity['role'], 'المقاول الرئيسي')

        missing = self._run('update_team_entity', name='جهة غير موجودة', updates={'role': 'x'})
        self.assertEqual(missing['status'], 'error')

        removed = self._run('delete_team_entity', name='مكتب الرياض للاستشارات')
        self.assertEqual(removed['status'], 'success', removed.get('message'))
        with self.app.app_context():
            self.assertNotIn('مكتب الرياض للاستشارات',
                             [item['name'] for item in db.get_team_entities(self.tenant)])

    # ── Fields: add and disable freely, never delete an original one ───────

    def test_agent_may_delete_only_the_fields_it_added(self):
        with self.app.app_context():
            fields = db.get_fields(self.tenant, active_only=False)
            original = next(field for field in fields if not field.get('is_custom'))

        refused = self._run('delete_field', field_key=original['field_key'])
        self.assertEqual(refused['status'], 'error')
        self.assertIn('لا يمكن حذف الحقل الأساسي', refused['message'])
        with self.app.app_context():
            still_there = db.get_fields(self.tenant, active_only=False)
        self.assertIn(original['field_key'], [field['field_key'] for field in still_there])

        # Disabling an original field is allowed, and it can be brought back.
        disabled = self._run('update_field', field_key=original['field_key'], updates={'is_active': 0})
        self.assertEqual(disabled['status'], 'success', disabled.get('message'))
        self._run('update_field', field_key=original['field_key'], updates={'is_active': 1})

        created = self._run('add_field', field_label='حقل تجريبي للوكيل', field_type='text',
                            section_key='basic')
        self.assertEqual(created['status'], 'success', created.get('message'))
        deleted = self._run('delete_field', field_label='حقل تجريبي للوكيل')
        self.assertEqual(deleted['status'], 'success', deleted.get('message'))

    # ── Company settings the agent could not reach before ─────────────────

    def test_agent_can_set_map_styles_and_lock_the_slide_count(self):
        result = self._run('update_branding', map_style_overview='roadmap',
                           map_style_landmarks='hybrid', default_map_type='roadmap',
                           lock_slide_count=True, draw_compass=False)
        self.assertEqual(result['status'], 'success', result.get('message'))
        with self.app.app_context():
            branding = db.get_branding(self.tenant)
        self.assertEqual(branding['map_style_overview'], 'roadmap')
        self.assertEqual(branding['map_style_landmarks'], 'hybrid')
        self.assertEqual(branding['default_map_type'], 'roadmap')
        self.assertEqual(branding['lock_slide_count'], 1)
        self.assertEqual(branding['draw_compass'], 0)

    # ── The generation prompt ─────────────────────────────────────────────

    def test_generation_rules_written_by_the_agent_reach_the_slide_prompt(self):
        rules = 'ابدأ العرض بمحور الموقع قبل المكونات، واكتب المساحات بالمتر المربع دائمًا.'
        result = self._run('set_generation_rules', rules=rules)
        self.assertEqual(result['status'], 'success', result.get('message'))

        read_back = self._run('get_generation_rules')
        self.assertEqual(read_back['data']['rules'], rules)

        with self.app.app_context():
            branding = db.get_branding(self.tenant)
        prompt = build_design_rules(branding)
        self.assertIn(rules, prompt)
        # A company rule can add to the platform rules; it cannot license breaking them.
        self.assertIn('ممنوع اختراع أي معلومة', prompt)
        self.assertIn('فالقواعد الأساسية أعلاه هي التي تُطبَّق', prompt)

        cleared = self._run('set_generation_rules', rules='')
        self.assertEqual(cleared['status'], 'success')
        with self.app.app_context():
            self.assertNotIn(rules, build_design_rules(db.get_branding(self.tenant)))

    # ── Asking, reading files, and the model it runs on ───────────────────

    def test_agent_asks_instead_of_guessing_and_applies_nothing_that_turn(self):
        client = self.app.test_client()
        reply = _reply_with([
            {'tool': 'ask', 'params': {'question': 'أي حقل تقصد بالضبط؟'}},
            {'tool': 'update_branding', 'params': {'primary_color': '#ff0000'}},
        ], text='الطلب غير واضح')
        with self.app.app_context():
            before = db.get_branding(self.tenant)['primary_color']
        with patch.object(self.application_module, 'call_zai_chat', return_value=reply):
            response = client.post('/api/training-chat', headers=self._headers(),
                                   json={'message': 'عدّل الحقل'})

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertTrue(payload['awaitingAnswer'])
        self.assertIn('أي حقل تقصد بالضبط؟', payload['reply'])
        self.assertEqual([item['tool'] for item in payload['actions']], ['ask'])
        with self.app.app_context():
            self.assertEqual(db.get_branding(self.tenant)['primary_color'], before)

    def test_agent_reads_an_attached_pdf_and_sees_an_attached_image(self):
        client = self.app.test_client()
        import fitz

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 100), 'Coverage ratio is 45 percent')
        pdf_bytes = document.tobytes()
        document.close()
        pdf_uri = 'data:application/pdf;base64,' + base64.b64encode(pdf_bytes).decode()
        image_uri = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ'
                     'AAAAC0lEQVR42mP8DwQACfsD/WMmxY8AAAAASUVORK5CYII=')

        captured = {}

        def fake_chat(system_prompt, user_prompt, **kwargs):
            captured['system'] = system_prompt
            captured['kwargs'] = kwargs
            return _reply_with([], text='قرأت الملف')

        with patch.object(self.application_module, 'call_zai_chat', side_effect=fake_chat):
            response = client.post('/api/training-chat', headers=self._headers(), json={
                'message': 'اقرأ الاشتراطات المرفقة',
                'attachedFile': {'name': 'اشتراطات.pdf', 'dataUri': pdf_uri},
                'attachedImage': image_uri,
            })

        self.assertTrue(response.get_json()['success'], response.get_json())
        # The file content itself reaches the prompt, not a note saying a file exists.
        self.assertIn('Coverage ratio is 45 percent', captured['system'])
        self.assertIn('اشتراطات.pdf', captured['system'])
        self.assertEqual(captured['kwargs']['image_references'], [{'data_uri': image_uri}])
        # This agent changes company settings, so it runs on the reasoning model.
        self.assertEqual(captured['kwargs']['model'], self.application_module.SLIDE_TEXT_MODEL)
        self.assertEqual(captured['kwargs']['reasoning_effort'], 'medium')
        self.assertEqual(self.application_module.SLIDE_TEXT_MODEL, 'openai/gpt-5.6-sol')

    def test_agent_prompt_states_every_new_capability(self):
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        for marker in ('"tool": "list_team"', '"tool": "add_team_entity"',
                       '"tool": "update_team_entity"', '"tool": "delete_team_entity"',
                       '"tool": "get_generation_rules"', '"tool": "set_generation_rules"',
                       '"tool": "ask"'):
            self.assertIn(marker, app_source, marker)
        self.assertIn('اسأل بدل أن تخمّن', app_source)
        self.assertIn('الحقول الأصلية للنظام لا تُحذف', app_source)


if __name__ == '__main__':
    unittest.main()
