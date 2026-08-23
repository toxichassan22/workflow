"""Regression checks for the company font panel and the training-agent font tools.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import io
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
from design_templates import build_font_css


class FontWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        # Uploads must live on the same drive as app.py: os.path.relpath fails across drives.
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'font-workflows.db')

        # Import only after redirecting DB_PATH: app.py initializes its database at import time.
        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        # Uploaded font files written by this suite stay in the temporary folder.
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            cls.tenant = db.create_tenant('Font Co', 'fonts@example.test', 'hash-a', 'font-co')
            cls.other_tenant = db.create_tenant('Other Co', 'other@example.test', 'hash-b', 'other-co')
            cls.font_ar = db.create_sag_font('Cairo', 'Cairo', 'arabic', 'regular', source_type='preset', source_data='Cairo')
            cls.font_lat = db.create_sag_font('Cairo', 'Cairo', 'latin', 'regular', source_type='preset', source_data='Cairo')

        cls.token = auth.create_token(
            cls.tenant, 'fonts@example.test', user_id=None, user_name='Font Co', user_role='company_admin'
        )
        cls.other_token = auth.create_token(
            cls.other_tenant, 'other@example.test', user_id=None, user_name='Other Co', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    @staticmethod
    def _headers(token):
        return {'Authorization': f'Bearer {token}'}

    def setUp(self):
        # Each test starts from a clean font-selection slate.
        with self.app.app_context():
            for script in ('arabic', 'latin'):
                for weight in ('light', 'regular', 'medium', 'bold', 'black'):
                    db.delete_tenant_font_selection(self.tenant, script, weight)
                    db.delete_tenant_font_selection(self.other_tenant, script, weight)

    # ── Branding font API ─────────────────────────────────────────────────

    def test_get_branding_fonts_lists_available_central_fonts(self):
        client = self.app.test_client()
        resp = client.get('/api/branding/fonts', headers=self._headers(self.token))
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['selections'], [])
        families = {f['font_family'] for f in payload['available']}
        self.assertIn('Cairo', families)

    def test_put_and_delete_branding_font_selection(self):
        client = self.app.test_client()
        resp = client.put('/api/branding/fonts', headers=self._headers(self.token), json={
            'script': 'arabic', 'weight': 'regular', 'font_id': self.font_ar,
        })
        self.assertEqual(resp.status_code, 200)
        selections = resp.get_json()['selections']
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]['font_id'], self.font_ar)
        self.assertNotIn('custom_font_data', selections[0])

        resp = client.delete('/api/branding/fonts/arabic/regular', headers=self._headers(self.token))
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.get_tenant_font_selection(self.tenant, 'arabic', 'regular'))

    def test_put_rejects_unknown_font_id(self):
        client = self.app.test_client()
        resp = client.put('/api/branding/fonts', headers=self._headers(self.token), json={
            'script': 'arabic', 'weight': 'regular', 'font_id': 'missing-font',
        })
        self.assertEqual(resp.status_code, 404)

    def test_auto_upload_detects_and_selects_uploaded_font(self):
        font_file = ROOT / 'assets' / 'fonts' / 'BahijTheSansArabic-Bold.ttf'
        self.assertTrue(font_file.exists(), 'bundled test font is missing')
        client = self.app.test_client()
        with open(font_file, 'rb') as fh:
            resp = client.post(
                '/api/branding/fonts/auto-upload',
                headers=self._headers(self.token),
                data={'font': (io.BytesIO(fh.read()), 'BahijTheSansArabic-Bold.ttf')},
                content_type='multipart/form-data',
            )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['detected']['family'])
        self.assertTrue(payload['selections'], 'auto-upload must select the font for detected scripts')
        with self.app.app_context():
            for sel in db.get_tenant_font_selections(self.tenant):
                self.assertTrue(sel['custom_font_path'])
                full_path = os.path.join(self.application_module.UPLOADS_DIR, self.tenant, 'fonts',
                                         os.path.basename(sel['custom_font_path']))
                self.assertTrue(os.path.exists(full_path), full_path)
                # Selections are tenant-scoped: the other tenant must not see them.
                self.assertEqual(db.get_tenant_font_selections(self.other_tenant), [])

    def test_auto_upload_new_family_replaces_stale_weights(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id='sag-default-arabic-regular')
            db.set_tenant_font_selection(self.tenant, 'arabic', 'bold', font_id='sag-default-arabic-bold')
            db.update_branding(self.tenant, font_family='The Sans Arabic')
        font_file = ROOT / 'assets' / 'fonts' / 'BahijTheSansArabic-Bold.ttf'
        client = self.app.test_client()
        resp = client.post(
            '/api/branding/fonts/auto-upload',
            headers=self._headers(self.token),
            data={'font': (io.BytesIO(font_file.read_bytes()), 'DifferentCompanyFont-Bold.ttf')},
            content_type='multipart/form-data',
        )
        self.assertEqual(resp.status_code, 200)
        detected = resp.get_json()['detected']
        with self.app.app_context():
            selections = [s for s in db.get_tenant_font_selections(self.tenant) if s['script'] == 'arabic']
        self.assertTrue(selections)
        self.assertTrue(all(s['font_id'] is None for s in selections))
        self.assertEqual({s['weight'] for s in selections}, {detected['weight']})

    def test_pdf_css_uses_single_uploaded_weight_for_all_text_weights(self):
        font_file = ROOT / 'assets' / 'fonts' / 'BahijTheSansArabic-Bold.ttf'
        raw = font_file.read_bytes()
        import base64
        import json
        payload = json.dumps({'data': base64.b64encode(raw).decode('ascii'), 'format': 'truetype'})
        with self.app.app_context():
            db.set_tenant_font_selection(
                self.tenant, 'arabic', 'medium', custom_font_data=payload,
                custom_font_path='uploads/test/fonts/custom.ttf'
            )
            css, family = build_font_css({'font_family': 'Custom Company Font'}, self.tenant, embed=True)
        alias = f'tenant-managed-{self.tenant}'
        self.assertIn(f"font-family:'{alias}'", css)
        self.assertIn('font-weight:100 900', css)
        self.assertNotIn("font-family:'The Sans Arabic'", css)
        self.assertTrue(family.startswith(f"'{alias}'"))

    def test_pdf_css_combines_uploaded_weights_under_one_family(self):
        font_file = ROOT / 'assets' / 'fonts' / 'BahijTheSansArabic-Bold.ttf'
        raw = font_file.read_bytes()
        import base64
        import json
        payload = json.dumps({'data': base64.b64encode(raw).decode('ascii'), 'format': 'truetype'})
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', custom_font_data=payload)
            db.set_tenant_font_selection(self.tenant, 'arabic', 'bold', custom_font_data=payload)
            css, _family = build_font_css({}, self.tenant, embed=True)
        alias = f'tenant-managed-{self.tenant}'
        self.assertGreaterEqual(css.count(f"font-family:'{alias}'"), 2)
        self.assertIn('font-weight:400', css)
        self.assertIn('font-weight:700', css)

    def test_pdf_css_keeps_arabic_and_latin_system_faces_in_one_unicode_family(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id='sag-default-arabic-regular')
            db.set_tenant_font_selection(self.tenant, 'latin', 'regular', font_id='sag-default-latin-regular')
            css, family = build_font_css({}, self.tenant, embed=True)
        alias = f'tenant-managed-{self.tenant}'
        self.assertIn("src:local('Arial')", css)
        self.assertIn('font-weight:100 900', css)
        self.assertIn('U+0600-06FF', css)
        self.assertIn('U+0000-024F', css)
        self.assertTrue(family.startswith(f"'{alias}'"))

    # ── The font must survive the slide it is applied to ──────────────────

    def test_slide_font_declarations_never_beat_the_company_font(self):
        """A slide carried its own font, and in the preview an !important block won."""
        from design_templates import build_design_rules, sanitize_slide_html_for_export

        with self.app.app_context():
            rules = build_design_rules(db.get_branding(self.tenant) or {})
        # The prompt used to bake a display font name into every slide while the loaded face is a
        # per-tenant alias, so the two never matched.
        self.assertIn('ممنوع كتابة font-family', rules)
        base_slide = rules[rules.index('## الشريحة الأساسية'):]
        self.assertNotIn('font-family:', base_slide.split('CSS inline')[0])

        hostile = ('<div class="slide" style="font-family:Arial;padding:10px">'
                   '<style>.slide,.slide *{font-family:"Courier New" !important}</style>'
                   '<h1 style="font-size:48px;font-family:Tahoma">عنوان</h1></div>')
        cleaned = sanitize_slide_html_for_export(hostile)
        self.assertNotIn('font-family', cleaned)
        self.assertIn('padding:10px', cleaned)
        self.assertIn('font-size:48px', cleaned)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function stripSlideFontDeclarations(html)', index_source)
        self.assertIn('let cleanHtml = stripSlideFontDeclarations(html);', index_source)

    def test_font_status_reports_whether_a_real_face_will_render(self):
        client = self.app.test_client()
        response = client.get('/api/branding/font-status', headers=self._headers(self.token))
        self.assertEqual(response.status_code, 200, response.get_json())
        status = response.get_json()['status']
        # The platform default resolves to the bundled faces, which are not Git LFS files.
        self.assertEqual(status['source'], 'platform default')
        self.assertTrue(status['willRenderRealFont'], status)
        self.assertEqual(status['renders'], 'embedded file')
        self.assertGreater(status['embeddedFiles'], 0)
        self.assertFalse(status['localNameOnly'])
        self.assertIn('TheSansArabic-Light', status['bundledFaces'])

        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
        status = client.get('/api/branding/font-status',
                            headers=self._headers(self.token)).get_json()['status']
        self.assertEqual(status['source'], 'company selection')
        # Cairo is a Google face: it renders, but over the network rather than from a shipped file.
        self.assertEqual(status['renders'], 'google web font')
        self.assertTrue(status['willRenderRealFont'], status)

    def test_the_font_picker_is_per_script_and_states_what_is_applied(self):
        """One dropdown offering the two platform defaults could not change anything, ever.

        Arabic and Latin resolve independently, and a script with no selection keeps the platform
        default — so picking the default Latin face left every Arabic word exactly as it was.
        """
        client = self.app.test_client()
        status = client.get('/api/branding/font-status',
                            headers=self._headers(self.token)).get_json()['status']
        self.assertFalse(status['scripts']['arabic']['chosen'])
        self.assertFalse(status['scripts']['latin']['chosen'])
        self.assertTrue(status['scripts']['arabic']['font'])
        self.assertTrue(status['scripts']['latin']['font'])

        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
        status = client.get('/api/branding/font-status',
                            headers=self._headers(self.token)).get_json()['status']
        self.assertTrue(status['scripts']['arabic']['chosen'])
        self.assertEqual(status['scripts']['arabic']['font'], 'Cairo')
        # The other script is untouched, and the reader is told so instead of guessing.
        self.assertFalse(status['scripts']['latin']['chosen'])

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="presentationFontArabic"', index_source)
        self.assertIn('id="presentationFontLatin"', index_source)
        self.assertIn('async function selectPresentationScriptFont(script, fontId)', index_source)
        self.assertIn('async function renderPresentationFontStatus()', index_source)
        # The single combined picker is gone.
        self.assertNotIn('id="presentationFontSelect"', index_source)

    def test_a_font_name_with_no_source_still_renders_a_real_face(self):
        """A stored name with no file behind it silently fell back to the reader's Tahoma."""
        from design_templates import build_font_css

        with self.app.app_context():
            for script in ('arabic', 'latin'):
                for weight in ('light', 'regular', 'medium', 'bold', 'black'):
                    db.delete_tenant_font_selection(self.tenant, script, weight)
            db.update_branding(self.tenant, font_family='NoSuchFontAnywhere Bold')
            branding = db.get_branding(self.tenant)
            css, family_list = build_font_css(branding, self.tenant, embed=False)

        self.assertIn('@font-face', css)
        self.assertIn('base64,', css)
        # The requested name stays first in case the reading machine has it installed.
        self.assertTrue(family_list.startswith("'NoSuchFontAnywhere Bold'"), family_list)
        self.assertIn("'platform-fallback-arabic'", family_list)

        client = self.app.test_client()
        status = client.get('/api/branding/font-status',
                            headers=self._headers(self.token)).get_json()['status']
        self.assertTrue(status['willRenderRealFont'], status)
        with self.app.app_context():
            db.update_branding(self.tenant, font_family='The Sans Arabic')

    # ── Training-agent font tools ─────────────────────────────────────────

    def test_agent_list_fonts_tool(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
            result = self.application_module._execute_agent_action(self.tenant, {'tool': 'list_fonts'})
        self.assertEqual(result['status'], 'success')
        # The registry ships with seeded defaults plus the two Cairo rows created in setUpClass.
        cairo_fonts = [f for f in result['data']['available'] if f['font_family'] == 'Cairo']
        self.assertEqual(len(cairo_fonts), 2)
        self.assertEqual(result['data']['current'][0]['font_id'], self.font_ar)

    def test_agent_set_font_by_name_applies_to_all_scripts(self):
        with self.app.app_context():
            result = self.application_module._execute_agent_action(
                self.tenant, {'tool': 'set_font', 'params': {'font_query': 'Cairo'}}
            )
            self.assertEqual(result['status'], 'success', result.get('message'))
            self.assertEqual(
                db.get_tenant_font_selection(self.tenant, 'arabic', 'regular')['font_id'], self.font_ar
            )
            self.assertEqual(
                db.get_tenant_font_selection(self.tenant, 'latin', 'regular')['font_id'], self.font_lat
            )

    def test_agent_set_font_resets_to_default(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
            result = self.application_module._execute_agent_action(
                self.tenant, {'tool': 'set_font', 'params': {'font_query': 'default'}}
            )
            self.assertEqual(result['status'], 'success', result.get('message'))
            self.assertEqual(db.get_tenant_font_selections(self.tenant), [])

    def test_agent_set_font_rejects_unknown_font(self):
        with self.app.app_context():
            result = self.application_module._execute_agent_action(
                self.tenant, {'tool': 'set_font', 'params': {'font_query': 'NoSuchFont'}}
            )
        self.assertEqual(result['status'], 'error')
        self.assertIn('NoSuchFont', result['message'])

    def test_agent_system_state_includes_font_section(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
            state = self.application_module._build_agent_system_state(self.tenant)
        self.assertIn('الخطوط', state)
        self.assertIn('Cairo', state)

    # ── Training-chat fallback intents (AI unavailable) ───────────────────

    def test_training_chat_font_intent_without_ai(self):
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat', side_effect=RuntimeError('AI down')):
            resp = client.post('/api/training-chat', headers=self._headers(self.token), json={
                'message': 'غيّر الخط إلى Cairo',
            })
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload['success'])
        font_actions = [a for a in payload['actions'] if a.get('tool') == 'set_font']
        self.assertTrue(font_actions, payload)
        self.assertEqual(font_actions[0]['status'], 'success')
        with self.app.app_context():
            self.assertEqual(
                db.get_tenant_font_selection(self.tenant, 'arabic', 'regular')['font_id'], self.font_ar
            )

    def test_training_chat_font_reset_intent_without_ai(self):
        with self.app.app_context():
            db.set_tenant_font_selection(self.tenant, 'arabic', 'regular', font_id=self.font_ar)
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat', side_effect=RuntimeError('AI down')):
            resp = client.post('/api/training-chat', headers=self._headers(self.token), json={
                'message': 'رجّع الخط الافتراضي',
            })
        self.assertEqual(resp.status_code, 200)
        font_actions = [a for a in resp.get_json()['actions'] if a.get('tool') == 'set_font']
        self.assertTrue(font_actions)
        with self.app.app_context():
            self.assertEqual(db.get_tenant_font_selections(self.tenant), [])

    def test_training_chat_slide_plan_word_does_not_trigger_font_intent(self):
        """'خطة' contains the letters خط — it must never trigger the font fallback."""
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat', side_effect=RuntimeError('AI down')):
            resp = client.post('/api/training-chat', headers=self._headers(self.token), json={
                'message': 'عدّل خطة الشرائح لو سمحت',
            })
        self.assertEqual(resp.status_code, 200)
        font_actions = [a for a in resp.get_json()['actions'] if a.get('tool') == 'set_font']
        self.assertEqual(font_actions, [])


if __name__ == '__main__':
    unittest.main()
