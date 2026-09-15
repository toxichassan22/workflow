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

FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '06-team.js', '07-project-form.js', '08-location-maps.js', '09-financial.js',
    '10-financial-report-timeline.js', '11-land-croquis.js', '12-files-media.js',
    '13-visual.js', '14-slides-gen.js', '15-slide-edit-chat.js',
    '16-presentations-export.js', '17-admin-boot.js', '18-omran-ops.js',
)


def read_frontend_text():
    """The full client source: shell + styles + scripts in load order."""
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    for name in ('assets/css/base.css', 'assets/css/project-form.css'):
        parts.append((ROOT / name).read_text(encoding='utf-8'))
    for name in FRONTEND_JS_ORDER:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


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

    # ── Permissions: the reported result must match what was applied ───────

    def test_set_permission_reports_the_change_it_applied(self):
        """Regression: the branch used `status_text` before defining it, so the
        permission was written and logged, then the tool still answered
        status='error' (UnboundLocalError) — the user could retry or believe
        the grant never happened."""
        with self.app.app_context():
            uid = db.create_user(self.tenant, 'موظف الصلاحيات',
                                 'perm-target@example.test', 'hash')
        try:
            granted = self._run('set_permission', user_email='perm-target@example.test',
                                permission='export_files', granted=True)
            self.assertEqual(granted['status'], 'success', granted.get('message'))
            self.assertIn('منح', granted['message'])
            with self.app.app_context():
                self.assertTrue(db.get_user_permissions(uid)['export_files'])

            # A string 'false' from the model must revoke, not count as truthy.
            revoked = self._run('set_permission', user_email='perm-target@example.test',
                                permission='export_files', granted='false')
            self.assertEqual(revoked['status'], 'success', revoked.get('message'))
            self.assertIn('سحب', revoked['message'])
            with self.app.app_context():
                self.assertFalse(db.get_user_permissions(uid)['export_files'])
        finally:
            with self.app.app_context():
                db.delete_user(uid)

    # ── The last-admin guard binds the agent like the user routes ──────────

    def test_agent_cannot_disable_the_last_company_admin(self):
        with self.app.app_context():
            admin_id = db.create_user(self.tenant, 'مدير وحيد', 'solo-admin@agent.test',
                                      'hash', role='company_admin')

        refused = self._run('toggle_user', user_email='solo-admin@agent.test', is_active=False)
        self.assertEqual(refused['status'], 'error')
        self.assertIn('آخر مدير شركة', refused['message'])
        with self.app.app_context():
            self.assertEqual(db.get_user_by_id(admin_id)['is_active'], 1)

        # With a second active admin the same tool disables normally.
        with self.app.app_context():
            db.create_user(self.tenant, 'مدير ثان', 'second-admin@agent.test',
                           'hash', role='company_admin')
        allowed = self._run('toggle_user', user_email='solo-admin@agent.test', is_active=False)
        self.assertEqual(allowed['status'], 'success', allowed.get('message'))
        with self.app.app_context():
            self.assertEqual(db.get_user_by_id(admin_id)['is_active'], 0)

    # ── The agent may not exceed the requester's own permissions ───────────

    def test_agent_tools_respect_the_requesters_own_permissions(self):
        """Regression: entering the agent needed only `training_data`, while its
        tools created users, granted permissions and rewrote company settings.
        Every tool now re-checks the permission its dedicated route requires."""
        client = self.app.test_client()
        with self.app.app_context():
            employee_id = db.create_user(self.tenant, 'موظف تدريب',
                                         'trainer@agent.test', 'hash')
            db.set_user_permission(employee_id, 'training_data', True)
            branding_before = db.get_branding(self.tenant)['primary_color']
        employee_headers = {'Authorization': 'Bearer ' + auth.create_token(
            self.tenant, 'trainer@agent.test', user_id=employee_id,
            user_name='موظف تدريب', user_role='employee')}
        try:
            reply = _reply_with([
                {'tool': 'add_user', 'params': {'name': 'مستخدم متسلل', 'email': 'sneaky@agent.test'}},
                {'tool': 'update_branding', 'params': {'primary_color': '#000000'}},
                {'tool': 'list_users'},
                {'tool': 'add_training', 'params': {'title': 'قاعدة', 'content': 'محتوى'}},
            ], text='نفذت كل المطلوب')
            with patch.object(self.application_module, 'call_zai_chat', return_value=reply):
                response = client.post('/api/training-chat', headers=employee_headers,
                                       json={'message': 'نفذ'})

            payload = response.get_json()
            self.assertTrue(payload['success'], payload)
            by_tool = {item.get('tool'): item for item in payload['actions']}
            for denied_tool in ('add_user', 'update_branding', 'list_users'):
                self.assertEqual(by_tool[denied_tool]['status'], 'error', denied_tool)
                self.assertEqual(by_tool[denied_tool]['error_code'], 'AGENT_PERMISSION_DENIED')
            self.assertIn('إدارة الموظفين', by_tool['add_user']['message'])
            # A tool inside the requester's own permission still runs.
            self.assertEqual(by_tool['add_training']['status'], 'success')
            with self.app.app_context():
                self.assertIsNone(db.get_user_by_email('sneaky@agent.test'))
                self.assertEqual(db.get_branding(self.tenant)['primary_color'], branding_before)

            # Granting manage_users re-opens exactly those tools — nothing else.
            with self.app.app_context():
                db.set_user_permission(employee_id, 'manage_users', True)
            reply2 = _reply_with([
                {'tool': 'add_user', 'params': {'name': 'مستخدم جديد',
                                                'email': 'sneaky@agent.test',
                                                'password': 'strongpass1'}},
                {'tool': 'update_branding', 'params': {'primary_color': '#000000'}},
            ])
            with patch.object(self.application_module, 'call_zai_chat', return_value=reply2):
                response2 = client.post('/api/training-chat', headers=employee_headers,
                                        json={'message': 'نفذ'})
            by_tool2 = {item.get('tool'): item for item in response2.get_json()['actions']}
            self.assertEqual(by_tool2['add_user']['status'], 'success', by_tool2['add_user'])
            self.assertEqual(by_tool2['update_branding']['status'], 'error')
            self.assertEqual(by_tool2['update_branding']['error_code'], 'AGENT_PERMISSION_DENIED')
            with self.app.app_context():
                self.assertIsNotNone(db.get_user_by_email('sneaky@agent.test'))
                self.assertEqual(db.get_branding(self.tenant)['primary_color'], branding_before)
        finally:
            with self.app.app_context():
                for email in ('trainer@agent.test', 'sneaky@agent.test'):
                    user = db.get_user_by_email(email)
                    if user:
                        db.delete_user(user['id'])

    # ── Adding employees never goes through a default password ────────────

    def test_agent_add_user_never_falls_back_to_a_default_password(self):
        """ISS-008: the tool used to substitute '123456' when the model sent
        no password and then repeated that password back in the chat reply."""
        # No password at all -> one-time setup link, first login must set one.
        created = self._run('add_user', name='موظف بلا كلمة', email='nopw@agent.test',
                            role='employee')
        self.assertEqual(created['status'], 'success', created.get('message'))
        setup_url = (created.get('data') or {}).get('setupUrl', '')
        self.assertIn('/set-password/', setup_url)
        self.assertNotIn('123456', created['message'])
        with self.app.app_context():
            user = db.get_user_by_email('nopw@agent.test')
            self.assertEqual(user['require_password_change'], 1)
            token_row = db.get_password_setup_token(setup_url.rsplit('/', 1)[-1])
            self.assertIsNotNone(token_row)
            self.assertEqual(token_row['user_id'], user['id'])

        # A weak password is refused, not silently accepted.
        weak = self._run('add_user', name='موظف ضعيف', email='weak@agent.test',
                         password='123456')
        self.assertEqual(weak['status'], 'error')
        with self.app.app_context():
            self.assertIsNone(db.get_user_by_email('weak@agent.test'))

        # A policy-compliant password is honoured and never echoed back.
        strong = self._run('add_user', name='موظف قوي', email='strong@agent.test',
                           password='AgentPass123')
        self.assertEqual(strong['status'], 'success', strong.get('message'))
        self.assertNotIn('AgentPass123', strong['message'])
        with self.app.app_context():
            user = db.get_user_by_email('strong@agent.test')
            self.assertEqual(user['require_password_change'], 0)
            self.assertTrue(auth.verify_password('AgentPass123', user['password_hash']))

    def test_agent_prompt_documents_the_add_user_contract(self):
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('"tool": "add_user"', app_source)
        # The contract must rule out invented defaults and echoed secrets.
        self.assertNotIn("or '123456'", app_source)
        self.assertIn('لا تخترع كلمة مرور افتراضية', app_source)

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

    def test_workspace_slide_edit_resolves_company_and_project_logos(self):
        """Agent slide edits must use the same logo-aware finalizer as generation."""
        client_html = '<div class="slide" style="width:1280px;height:720px;"><div>محتوى</div></div>'
        response = _reply_with([], text=json.dumps({
            'html': client_html,
            'response': 'تم تحديث الشريحة',
        }, ensure_ascii=False))
        workspace = {
            'projectData': {
                'project_name': 'مشروع تجريبي',
                'project_logo_file_id': 'project-logo-1',
            },
            'slidesData': [{
                'title': 'نبذة عن المشروع',
                'type': 'content',
                'html': '<div class="slide" style="width:1280px;height:720px;"><div>قديم</div></div>',
            }],
        }
        with self.app.app_context():
            db.update_branding(self.tenant, logo_path=f'/tenant-assets/{self.tenant}/logo')
            with patch.object(self.application_module, 'call_zai_chat', return_value=response) as mocked:
                result = self.application_module._execute_agent_action(
                    self.tenant,
                    {'tool': 'edit_workspace_slide', 'params': {
                        'slide_index': 0,
                        'instruction': 'أضف شعار الشركة وشعار المشروع في موضع الهوية المخصص',
                    }},
                    workspace=workspace,
                )

        self.assertEqual(result['status'], 'success', result)
        rendered = result['data']['slidesData'][0]['html']
        self.assertIn(f'/tenant-assets/{self.tenant}/logo', rendered)
        self.assertIn('/api/project-files/project-logo-1', rendered)
        self.assertNotIn('##LOGO##', rendered)
        self.assertNotIn('##PROJECT_LOGO##', rendered)
        self.assertIn('##LOGO##', mocked.call_args.args[0])
        self.assertIn('##PROJECT_LOGO##', mocked.call_args.args[0])

    def test_workspace_slide_edit_resolves_selected_team_logo(self):
        """A team entity logo must stay distinct from the tenant/company logo."""
        team_html = '<div class="slide" style="width:1280px;height:720px;"><img src="##TEAM_LOGO_1##" alt="Vision Gate"></div>'
        response = _reply_with([], text=json.dumps({
            'html': team_html,
            'response': 'تمت إضافة شعار الجهة',
        }, ensure_ascii=False))
        workspace = {
            'projectData': {
                'project_name': 'مشروع تجريبي',
                'team_selection': json.dumps({
                    'excluded': [],
                    'roles': {},
                    'local': [{
                        'localId': 'vision-gate',
                        'name': 'Vision Gate',
                        'role': 'التطوير',
                        'logoFileId': 'team-logo-1',
                    }],
                }, ensure_ascii=False),
            },
            'slidesData': [{
                'title': 'فريق العمل',
                'type': 'content',
                'html': '<div class="slide" style="width:1280px;height:720px;"><div>قديم</div></div>',
            }],
        }
        with self.app.app_context():
            with patch.object(self.application_module, '_generation_project_image_url',
                              return_value='/uploads/creative/team-logo-1.png'), \
                    patch.object(self.application_module, 'call_zai_chat', return_value=response) as mocked:
                result = self.application_module._execute_agent_action(
                    self.tenant,
                    {'tool': 'edit_workspace_slide', 'params': {
                        'slide_index': 0,
                        'instruction': 'أضف شعار Vision Gate في مكانه المخصص داخل فريق العمل',
                    }},
                    workspace=workspace,
                )

        self.assertEqual(result['status'], 'success', result)
        rendered = result['data']['slidesData'][0]['html']
        self.assertIn('/uploads/creative/team-logo-1.png', rendered)
        self.assertNotIn('##TEAM_LOGO_1##', rendered)
        self.assertIn('Vision Gate', mocked.call_args.args[0])
        self.assertIn('##TEAM_LOGO_1##', mocked.call_args.args[0])

    def test_designer_chat_distinguishes_named_team_logo_from_company_logo(self):
        module = self.application_module
        images = {'team_members': [{
            'name': 'Vision Gate', 'role': 'التطوير',
            'logo': '/uploads/creative/team-logo-1.png',
        }]}
        match = module._find_designer_team_logo_request(
            'لم يتم إضافة اللوجو في الشريحة 52 حل المشكلة',
            [{'role': 'user', 'content': 'أضف لوجو Vision Gate في الشريحة 52'}],
            images,
        )
        self.assertEqual(match['index'], 1)
        self.assertEqual(match['token'], '##TEAM_LOGO_1##')
        self.assertIn('TEAM_LOGO_1', module._designer_team_logo_context(images))
        fallback = module._inject_team_logo_fallback(
            '<div class="slide"><div>محتوى</div></div>', match['logo'], match['index'])
        self.assertIn(match['logo'], fallback)
        self.assertIn('background:#0c2340', fallback)
        self.assertNotIn('##LOGO##', fallback)

    def test_designer_chat_inserts_the_selected_team_logo_on_named_slide(self):
        client = self.app.test_client()
        project_data = {
            'team_selection': json.dumps({'excluded': [], 'roles': {}, 'local': [{
                'localId': 'vision-gate', 'name': 'Vision Gate',
                'role': 'التطوير', 'logoFileId': 'team-logo-1',
            }]}, ensure_ascii=False),
        }
        slides = [{
            'title': 'فريق العمل', 'type': 'content',
            'html': '<div class="slide"><div>محتوى</div></div>',
        }]
        with patch.object(self.application_module, '_generation_project_image_url',
                          return_value='/uploads/creative/team-logo-1.png'), \
                patch.object(self.application_module, '_designer_edit_slide',
                             return_value=(slides[0]['html'], 'تمت إضافة الشعار')):
            response = client.post('/api/designer-chat', headers=self._headers(), json={
                'message': 'أضف لوجو Vision Gate في الشريحة رقم 1',
                'projectData': project_data,
                'slidesData': slides,
                'slideIndex': 0,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()['data']
        self.assertEqual(payload['actions'][0]['tool'], 'insert_team_logo')
        self.assertIn('/uploads/creative/team-logo-1.png', payload['slidesData'][0]['html'])
        self.assertNotIn('##LOGO##', payload['slidesData'][0]['html'])

    def test_designer_chat_prioritizes_company_logo_panel_over_previous_team_context(self):
        module = self.application_module
        images = {'team_members': [{
            'name': 'Vision Gate', 'role': 'التطوير',
            'logo': '/uploads/creative/team-logo-1.png',
        }]}
        company_request = 'انقل لوجو شركة بوابة الرؤية بداخل المربع في يمين الشريحة'
        self.assertTrue(module._designer_company_logo_requested(company_request))
        self.assertIsNone(module._find_designer_team_logo_request(
            company_request,
            [{'role': 'user', 'content': 'أضف لوجو Vision Gate في الشريحة 52'}],
            images,
        ))
        fallback = module._inject_company_logo_panel_fallback(
            '<div class="slide"><div>55</div></div>', '/tenant-assets/company.png')
        self.assertIn('data-company-logo-placement="right-panel"', fallback)
        self.assertIn('right:54px;top:92px', fallback)
        self.assertIn('/tenant-assets/company.png', fallback)

    def test_presentation_preview_exposes_text_and_element_editing(self):
        source = read_frontend_text()
        self.assertIn('toggleSlideInlineEditing', source)
        self.assertIn('toggleSlideElementEditing', source)
        self.assertIn('commitSlideElementMove', source)
        self.assertIn('data-company-logo-placement', source)
        self.assertIn('تحريك العناصر', source)


if __name__ == '__main__':
    unittest.main()
