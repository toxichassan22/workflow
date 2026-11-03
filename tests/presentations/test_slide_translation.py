"""Deck translation: markup-preserving engine and its API.

The point of the feature is that the deck is NOT regenerated: the Arabic copy
stays byte-identical, the English copy keeps every tag, attribute, number and
image, and a translation that would damage the markup is refused for that unit
instead of being written.

Run as a module from the repo root like every other suite::

    python -m unittest tests.presentations.test_slide_translation
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import sitecustomize  # noqa: F401  (puts every modules/ folder on sys.path)

import auth
import db
import slide_translator

MAP = {
    'واحة النخيل السكنية': 'Palm Oasis Residences',
    'مشروع مجمع سكني': 'A residential complex project',
    'نبذة عن المشروع': 'Project overview',
    'الغلاف': 'Cover',
    'محتويات العرض': 'Table of contents',
}


def fake_translator(texts):
    """Deterministic stand-in for the model: swaps known phrases, keeps tokens."""
    out = []
    for text in texts:
        value = text
        for arabic, english in MAP.items():
            value = value.replace(arabic, english)
        out.append(value)
    return out


def drop_numbers(texts):
    return [re.sub(r'\d[\d,.]*', '', text) for text in texts]


def drop_placeholders(texts):
    return [re.sub(r'⟦\d+⟧', '', text) for text in texts]


class TranslationEngineTests(unittest.TestCase):
    def test_inline_markup_and_attributes_survive(self):
        html = (
            '<div class="slide" dir="rtl" style="color:#fff;width:1280px">'
            '<p>مشروع مجمع سكني <strong>واحة النخيل السكنية</strong> بمساحة 18,500 م²</p>'
            '</div>'
        )
        translated, stats = slide_translator.translate_html(html, fake_translator)
        self.assertIn('class="slide"', translated)
        self.assertIn('dir="rtl"', translated)
        self.assertIn('style="color:#fff;width:1280px"', translated)
        self.assertIn('<strong>Palm Oasis Residences</strong>', translated)
        self.assertIn('18,500', translated)
        self.assertGreaterEqual(stats['translated'], 1)

    def test_one_paragraph_split_by_strong_is_translated_as_one_unit(self):
        html = '<p>مشروع مجمع سكني <strong>واحة النخيل السكنية</strong></p>'
        sent = []

        def capture(texts):
            sent.extend(texts)
            return fake_translator(texts)

        slide_translator.translate_html(html, capture)
        self.assertEqual(len(sent), 1, sent)
        self.assertIn('⟦0⟧', sent[0])
        self.assertIn('⟦1⟧', sent[0])

    def test_a_translation_that_drops_a_number_is_refused(self):
        html = '<p>مساحة الأرض 18,500 م²</p>'
        translated, stats = slide_translator.translate_html(html, drop_numbers)
        self.assertEqual(translated, html)
        self.assertEqual(stats['translated'], 0)
        self.assertEqual(stats['skipped'], 1)

    def test_a_mangled_unit_is_retried_once_and_recovered(self):
        html = '<p>نبذة عن المشروع <strong>واحة النخيل السكنية</strong></p>'
        calls = []

        def flaky(texts):
            calls.append(len(texts))
            if len(calls) == 1:
                return [re.sub(r'⟦\d+⟧', '', text) for text in texts]
            return fake_translator(texts)

        translated, stats = slide_translator.translate_html(html, flaky)
        self.assertEqual(len(calls), 2, calls)
        self.assertEqual(stats['translated'], 1)
        self.assertIn('Project overview', translated)
        self.assertIn('<strong>', translated)

    def test_pieces_recover_when_even_the_retry_mangles_it(self):
        html = '<p>نبذة عن المشروع <strong>واحة النخيل السكنية</strong></p>'

        def mangles_units(texts):
            if any('⟦' in text for text in texts):
                return [re.sub(r'⟦\d+⟧', '', text) for text in texts]
            return fake_translator(texts)

        translated, stats = slide_translator.translate_html(html, mangles_units)
        self.assertIn('<strong>Palm Oasis Residences</strong>', translated)
        self.assertIn('Project overview', translated)
        self.assertEqual(stats['skipped'], 0)

    def test_a_translation_that_drops_a_placeholder_is_refused(self):
        html = '<p>نبذة عن المشروع <strong>واحة النخيل السكنية</strong></p>'
        translated, _ = slide_translator.translate_html(html, drop_placeholders)
        self.assertEqual(translated, html)
        self.assertIn('<strong>', translated)

    def test_style_and_script_are_never_sent(self):
        html = (
            '<div><style>.x{content:"الغلاف"}</style>'
            '<script>var label="الغلاف";</script><p>الغلاف</p></div>'
        )
        sent = []

        def capture(texts):
            sent.extend(texts)
            return fake_translator(texts)

        translated, _ = slide_translator.translate_html(html, capture)
        self.assertEqual(len(sent), 1, sent)
        self.assertIn('.x{content:"الغلاف"}', translated)
        self.assertIn('var label="الغلاف"', translated)
        self.assertIn('<p>Cover</p>', translated)

    def test_latin_only_text_is_not_sent(self):
        html = '<p>Marina Gate 2026</p>'
        sent = []
        slide_translator.translate_html(html, lambda texts: sent.extend(texts) or texts)
        self.assertEqual(sent, [])

    def test_titles_and_index_entries_are_translated_and_original_untouched(self):
        slides = [{
            'title': 'الغلاف',
            'html': '<div class="slide">الغلاف</div>',
            'indexEntries': [{'title': 'نبذة عن المشروع'}, {'title': 'Fixed'}],
        }]
        translated, stats = slide_translator.translate_slides(slides, fake_translator)
        self.assertEqual(translated[0]['title'], 'Cover')
        self.assertEqual(translated[0]['indexEntries'][0]['title'], 'Project overview')
        self.assertEqual(translated[0]['indexEntries'][1]['title'], 'Fixed')
        self.assertEqual(slides[0]['title'], 'الغلاف')
        self.assertEqual(slides[0]['indexEntries'][0]['title'], 'نبذة عن المشروع')
        self.assertEqual(stats['titles'], 2)

    def test_batches_are_split_and_reassembled_in_order(self):
        html = ''.join('<p>الغلاف %d</p>' % index for index in range(45))
        calls = []

        def translate(texts):
            calls.append(list(texts))
            return fake_translator(texts)

        translated, stats = slide_translator.translate_html(html, translate)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(stats['units'], 45)
        self.assertEqual(translated.count('<p>Cover '), 45)

    def test_a_provider_failure_leaves_every_unit_arabic(self):
        def explode(texts):
            raise RuntimeError('provider down')

        html = '<p>الغلاف</p><p>نبذة عن المشروع</p>'
        translated, stats = slide_translator.translate_html(html, explode)
        self.assertEqual(translated, html)
        self.assertEqual(stats['translated'], 0)

    def test_parse_response_tolerates_fences_and_missing_items(self):
        content = '```json\n{"items":[{"id":0,"text":"Cover"}]}\n```'
        self.assertEqual(slide_translator.parse_batch_response(content, 2), ['Cover', None])
        self.assertEqual(slide_translator.parse_batch_response('not json', 2), [None, None])

    def test_glossary_replaces_the_arabic_brand_in_the_output(self):
        html = '<p>شركة لاندلوم للتطوير العقاري</p>'

        def keep(texts):
            return ['Company ' + text for text in texts]

        translated, _ = slide_translator.translate_html(
            html, keep, glossary={'شركة لاندلوم': 'LandLoom'})
        self.assertIn('LandLoom', translated)
        self.assertNotIn('شركة لاندلوم', translated)

    def test_prompt_carries_the_protected_names(self):
        prompt = slide_translator.translation_prompt({'شركة لاندلوم': 'LandLoom'})
        self.assertIn('شركة لاندلوم', prompt)
        self.assertIn('LandLoom', prompt)
        self.assertIn('Names', prompt)

    def test_deck_has_arabic(self):
        self.assertTrue(slide_translator.deck_has_arabic([{'html': '<p>الغلاف</p>'}]))
        self.assertFalse(slide_translator.deck_has_arabic([{'html': '<p>Cover</p>'}]))
        self.assertFalse(slide_translator.deck_has_arabic([]))


class PresentationTranslationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'translation-api.db')
        import app as application
        cls.module = application
        cls.app = application.app
        cls.app.config['TESTING'] = True
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant(
                'Translation Tenant', 'translation@example.test', 'hash', 'translation-tenant')
            # The owner's English spelling of the company name is the glossary
            # source; without it the model invents a transliteration per run.
            db.update_tenant(cls.tenant, company_name='شركة لاندلوم', company_name_en='LandLoom')
        cls.headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.tenant, 'translation@example.test',
            user_name='Translator', user_role='company_admin')}

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.close_db()
        db.DB_PATH = cls.original_db_path
        cls.temp.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        self.model_patch = patch.object(self.module, 'TRANSLATION_MODEL', 'test/translator')
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def _create(self):
        response = self.client.post('/api/presentations', headers=self.headers, json={
            'title': 'واحة النخيل السكنية',
            'projectData': {'project_name': 'واحة النخيل السكنية', 'city': 'جدة'},
            'slidesData': [{
                'title': 'الغلاف',
                'type': 'cover',
                'html': ('<div class="slide" dir="rtl" style="background:#1a1a1a">'
                         '<h1>واحة النخيل السكنية</h1>'
                         '<p>شركة لاندلوم للتطوير العقاري</p>'
                         '<p>مشروع مجمع سكني بمساحة 18,500 م²</p></div>'),
                'indexEntries': [{'title': 'نبذة عن المشروع'}],
            }],
            'expectedRevision': 0,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def _fake_chat(self, system_prompt, user_content, **kwargs):
        payload = json.loads(user_content)
        items = []
        for item in payload['items']:
            text = item['text']
            for arabic, english in MAP.items():
                text = text.replace(arabic, english)
            items.append({'id': item['id'], 'text': text})
        return {'content': json.dumps({'items': items}, ensure_ascii=False)}

    def test_company_english_name_reaches_the_prompt_and_the_copy(self):
        created = self._create()
        prompts = []

        def chat(system_prompt, user_content, **kwargs):
            prompts.append(system_prompt)
            payload = json.loads(user_content)
            items = [{'id': item['id'], 'text': 'Company ' + item['text']}
                     for item in payload['items']]
            return {'content': json.dumps({'items': items}, ensure_ascii=False)}

        with patch.object(self.module, 'call_text_chat', side_effect=chat), \
                patch.object(self.module, 'extract_chat_content',
                             side_effect=lambda response, label=None: response.get('content', '')):
            response = self.client.post(
                '/api/presentations/%s/translate' % created['presentationId'],
                headers=self.headers, json={'targetLang': 'en'})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertTrue(any('LandLoom' in prompt for prompt in prompts), prompts)
        translated = self.client.get(
            '/api/presentations/%s' % response.get_json()['presentationId'],
            headers=self.headers).get_json()['presentation']
        html = translated['slidesData'][0]['html']
        self.assertIn('LandLoom', html)
        self.assertNotIn('شركة لاندلوم', html)

    def test_translation_spend_is_attributed_to_the_translate_flow(self):
        """Deck translation is its own spend, not "other".

        The metering context keeps a flow only when it is in AI_USAGE_FLOWS;
        anything else is stored as 'other', which hid this feature's cost
        inside the catch-all bucket.
        """
        self.assertIn('translate', self.module.AI_USAGE_FLOWS)

    def test_translate_creates_english_copy_and_keeps_the_original(self):
        created = self._create()
        with patch.object(self.module, 'call_text_chat', side_effect=self._fake_chat), \
                patch.object(self.module, 'extract_chat_content',
                             side_effect=lambda response, label=None: response.get('content', '')):
            response = self.client.post(
                '/api/presentations/%s/translate' % created['presentationId'],
                headers=self.headers, json={'targetLang': 'en'})
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertNotEqual(body['presentationId'], created['presentationId'])

        original = self.client.get(
            '/api/presentations/%s' % created['presentationId'], headers=self.headers).get_json()['presentation']
        self.assertIn('واحة النخيل السكنية', original['slidesData'][0]['html'])

        translated = self.client.get(
            '/api/presentations/%s' % body['presentationId'], headers=self.headers).get_json()['presentation']
        html = translated['slidesData'][0]['html']
        self.assertIn('Palm Oasis Residences', html)
        self.assertIn('18,500', html)
        self.assertIn('dir="rtl"', html)
        self.assertIn('background:#1a1a1a', html)
        self.assertEqual(translated['slidesData'][0]['title'], 'Cover')
        self.assertEqual(translated['projectData']['project_language'], 'en')

    def test_default_translation_model_slug_is_deepseek_flash(self):
        """TRANSLATION_MODEL defaults to deepseek/deepseek-v4.1-flash-1017."""
        app_path = ROOT / 'app.py'
        with open(app_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn(
            "TRANSLATION_MODEL = (os.environ.get('TRANSLATION_MODEL') or 'deepseek/deepseek-v4.1-flash-1017').strip()",
            src,
        )

    def test_translation_disables_reasoning_effort_for_fast_throughput(self):
        created = self._create()
        recorded_efforts = []

        def capture_chat(*args, **kwargs):
            recorded_efforts.append(kwargs.get('reasoning_effort'))
            return self._fake_chat(*args, **kwargs)

        with patch.object(self.module, 'call_text_chat', side_effect=capture_chat), \
                patch.object(self.module, 'extract_chat_content',
                             side_effect=lambda response, label=None: response.get('content', '')):
            response = self.client.post(
                '/api/presentations/%s/translate' % created['presentationId'],
                headers=self.headers, json={'targetLang': 'en'})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(len(recorded_efforts) > 0)
        self.assertTrue(all(effort == 'none' for effort in recorded_efforts))

    def test_translation_without_a_configured_model_is_refused(self):
        created = self._create()
        with patch.object(self.module, 'TRANSLATION_MODEL', ''):
            response = self.client.post(
                '/api/presentations/%s/translate' % created['presentationId'],
                headers=self.headers, json={'targetLang': 'en'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'TRANSLATION_MODEL_NOT_CONFIGURED')

    def test_unsupported_target_language_is_refused(self):
        created = self._create()
        response = self.client.post(
            '/api/presentations/%s/translate' % created['presentationId'],
            headers=self.headers, json={'targetLang': 'fr'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'UNSUPPORTED_TARGET_LANG')

    def test_a_provider_error_creates_no_copy(self):
        created = self._create()
        before = self.client.get('/api/presentations', headers=self.headers).get_json()['total']
        with patch.object(self.module, 'call_text_chat',
                          return_value={'error': {'message': 'wallet empty'}}):
            response = self.client.post(
                '/api/presentations/%s/translate' % created['presentationId'],
                headers=self.headers, json={'targetLang': 'en'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['code'], 'TRANSLATION_FAILED')
        after = self.client.get('/api/presentations', headers=self.headers).get_json()['total']
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
