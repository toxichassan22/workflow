"""The AI rules screen's generation-rules editor.

The stored value is one text that rides with every slide prompt, and the admin
agent writes it too. The editor owns only its marked block: everything the agent
typed outside it must survive a save from the screen, and the screen must never
save a rule set the prompt cannot carry.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.frontend_source import shell_text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class GenerationRulesEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'ai-rules-editor.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            # import app is a no-op when another suite already imported it.
            db.init_db()
            cls.tenant = db.create_tenant('Rules Co', 'rules@example.test', 'hash', 'rules-co')

        cls.token = auth.create_token(
            cls.tenant, 'rules@example.test', user_id=None, user_name='Rules Admin',
            user_role='company_admin',
        )
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _headers(self):
        return {'Authorization': 'Bearer ' + self.token}

    def _get(self):
        response = self.client.get('/api/ai-rules/generation-rules', headers=self._headers())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _post(self, payload, suffix=''):
        return self.client.post('/api/ai-rules/generation-rules' + suffix,
                                json=payload, headers=self._headers())

    def _branding_value(self):
        with self.app.app_context():
            return (db.get_branding(self.tenant) or {}).get('generation_rules') or ''

    def _seed(self, value):
        with self.app.app_context():
            db.update_branding(self.tenant, generation_rules=value)

    def test_round_trip_keeps_tone_terms_and_directives(self):
        payload = {
            'tone': 'analytical',
            'approved': ['صافي القيمة الحالية', 'معدل العائد الداخلي'],
            'banned': ['مضمون', 'فرصة ذهبية'],
            'directives': 'في دراسة السوق اعتمد القوة الشرائية في النطاق.',
        }
        saved = self._post(payload)
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))

        data = self._get()
        self.assertEqual(data['rules']['tone'], 'analytical')
        self.assertEqual(data['rules']['approved'], payload['approved'])
        self.assertEqual(data['rules']['banned'], payload['banned'])
        self.assertEqual(data['rules']['directives'], payload['directives'])
        self.assertIn('تحليلي تنفيذي', data['raw'])
        self.assertIn('مصطلحات ممنوعة: مضمون، فرصة ذهبية', data['raw'])

    def test_agent_rules_outside_the_block_survive_every_save(self):
        agent_text = 'استخدم مسمى «المنشأة» بدلاً من «الشركة» في كل النصوص.'
        self._seed(agent_text)

        first = self._post({'tone': 'marketing', 'approved': [], 'banned': ['مضمون'], 'directives': ''})
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(self._get()['rules']['extra'], agent_text)

        second = self._post({'tone': 'engineering', 'approved': [], 'banned': [], 'directives': 'توجيه'})
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        raw = self._branding_value()
        self.assertIn(agent_text, raw)
        self.assertEqual(raw.count(agent_text), 1)
        self.assertEqual(self._get()['rules']['tone'], 'engineering')

    def test_free_text_without_a_block_reads_as_agent_rules(self):
        self._seed('قاعدة قديمة كتبها الوكيل.')
        data = self._get()
        self.assertEqual(data['rules']['tone'], '')
        self.assertEqual(data['rules']['extra'], 'قاعدة قديمة كتبها الوكيل.')

    def test_blank_save_removes_the_block_but_keeps_agent_rules(self):
        agent_text = 'قاعدة الوكيل الباقية.'
        self._seed(agent_text)
        self._post({'tone': 'analytical', 'approved': [], 'banned': ['مضمون'], 'directives': 'x'})

        cleared = self._post({'tone': '', 'approved': [], 'banned': [], 'directives': ''})
        self.assertEqual(cleared.status_code, 200, cleared.get_data(as_text=True))
        raw = self._branding_value()
        self.assertEqual(raw, agent_text)

    def test_unknown_tone_is_refused(self):
        before = self._branding_value()
        response = self._post({'tone': 'poetic', 'approved': [], 'banned': [], 'directives': ''})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._branding_value(), before)

    def test_rules_longer_than_the_prompt_cap_are_refused(self):
        self._seed('ا' * 4500)
        response = self._post({
            'tone': 'analytical',
            'approved': [],
            'banned': [],
            'directives': 'ب' * 4000,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json().get('error_code'), 'RULES_TOO_LONG')

    def test_preview_does_not_write_and_shows_the_composed_text(self):
        self._seed('قاعدة الوكيل.')
        before = self._branding_value()
        response = self._post({'tone': 'marketing', 'approved': ['صافي الدخل التشغيلي'],
                               'banned': [], 'directives': ''}, suffix='/preview')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertIn('تسويقي راقٍ', body['composed'])
        self.assertIn('قاعدة الوكيل.', body['composed'])
        self.assertEqual(self._branding_value(), before)

    def test_every_save_is_recorded_in_the_rule_log(self):
        self._post({'tone': 'analytical', 'approved': [], 'banned': ['مضمون'], 'directives': ''})
        with self.app.app_context():
            rows = db.get_ai_rules_log(self.tenant, limit=5)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['rule_key'], 'set_generation_rules')
        self.assertEqual(rows[0]['rule_category'], 'company_generation_rules')
        self.assertIn('مضمون', rows[0]['new_value'])

    def test_screen_is_one_strip_and_a_three_field_drawer(self):
        html = shell_text()
        start = html.find('id="tenantAIRulesPage"')
        self.assertNotEqual(start, -1, 'tenantAIRulesPage must exist in the shell')
        end = html.find('</section>', start)
        page = html[start:end]
        for token in ('air-rules-strip', 'airRulesSummary', 'openAIRulesDrawer',
                      'aiRulesDrawer', 'airRulesToneGroup', 'airRulesBannedChips',
                      'airRulesDirectivesInput', 'aiRulesChatLog', 'aiRulesLogList'):
            self.assertIn(token, page)
        # The screen stays a chat: the chat log and its composer are still there.
        self.assertIn('sendAIRulesChat()', page)
        self.assertIn('aiRulesChatInput', page)

    def test_editor_script_is_wired_after_the_chat_script(self):
        orders = (ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py').read_text(encoding='utf-8')
        self.assertIn("'17-admin-boot/01b_ai_rules_editor.js'", orders)
        self.assertIn("'base/17_ai_rules.css'", orders)
        self.assertLess(orders.index("'17-admin-boot/01_training_rules.js'"),
                        orders.index("'17-admin-boot/01b_ai_rules_editor.js'"))


if __name__ == '__main__':
    unittest.main()
