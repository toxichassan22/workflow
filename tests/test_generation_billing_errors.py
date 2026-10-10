"""Billing/provider-credit failures must surface as billing failures.

A spend-capacity refusal (wallet, managed key limit, trial gate, provider
credits) used to collapse into a vague «تعذر التوليد» at the retry and
fallback layers. These tests pin the structured refusal: response dicts carry
``fatal``/``error_code``/``http_status``, exceptions carry ``fatal_ai_error``,
background jobs write the real reason, and the deterministic slide fallback
never pretends a refused generation succeeded.

The suite uses a temporary SQLite database and never calls a provider: HTTP is
always patched, so every assertion is about this repository's own behaviour.
"""

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
import slide_engine


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class GenerationBillingErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'billing-errors.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant(
                'Fatal Co', 'fatal@example.test', 'hash', 'fatal-co')

    @classmethod
    def tearDownClass(cls):
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _chat_call(self, payload, status_code, usage_ctx=None):
        module = self.application_module
        with patch.object(module, '_has_any_openrouter_key', return_value=True), \
             patch.object(module.requests, 'post',
                          return_value=_FakeResponse(payload, status_code)):
            return module.call_openrouter_chat(
                'sys', 'hi', max_tokens=10, usage_ctx=usage_ctx)

    # ── Provider refusal normalization ─────────────────────────────────

    def test_http_402_chat_call_returns_fatal_refusal(self):
        data = self._chat_call({'error': {'message': 'Insufficient credits'}}, 402)
        err = data.get('error') or {}
        self.assertTrue(err.get('fatal'))
        self.assertIn(err.get('error_code'),
                      ('INSUFFICIENT_CREDITS', 'PROVIDER_CREDITS_EXHAUSTED'))
        self.assertIn('رصيد', err.get('message') or '')
        # The provider's own wording survives for the cap-retry parsers.
        self.assertIn('Insufficient credits', err.get('provider_message') or '')

    def test_tenant_key_refusal_reads_as_company_wallet(self):
        module = self.application_module
        with patch.object(module, '_ai_call_uses_tenant_key', return_value=True):
            data = self._chat_call({'error': {'message': 'Insufficient credits'}}, 402)
        err = data.get('error') or {}
        self.assertEqual(err.get('error_code'), 'INSUFFICIENT_CREDITS')
        self.assertEqual(err.get('http_status'), 402)
        self.assertEqual(err.get('message'), module._COMPANY_CREDIT_EXHAUSTED_MSG)

    def test_unrelated_provider_error_is_not_normalized(self):
        data = self._chat_call({'error': {'message': 'model not found'}}, 404)
        err = data.get('error') or {}
        self.assertFalse(err.get('fatal'))
        self.assertIn('model not found', err.get('message') or '')

    def test_affordable_tokens_survive_normalization(self):
        module = self.application_module
        refusal = {'error': {'code': 402, 'message': (
            'This request requires more credits, or fewer max_tokens. '
            'You requested up to 60000 tokens, but can only afford 25898')}}
        data = self._chat_call(refusal['error'] and refusal, 402)
        # A 402 is still a spend-capacity refusal...
        self.assertTrue((data.get('error') or {}).get('fatal'))
        # ...but the quoted allowance stays readable for cap-shrink retries.
        self.assertEqual(module._chat_affordable_tokens(data), 25898)

    # ── Exception propagation ──────────────────────────────────────────

    def test_extract_chat_content_raises_fatal_for_refusal(self):
        module = self.application_module
        data = self._chat_call({'error': {'message': 'Insufficient credits'}}, 402)
        with self.assertRaises(module.FatalAICallError) as ctx:
            module.extract_chat_content(data, 'TEST')
        exc = ctx.exception
        self.assertTrue(exc.fatal_ai_error)
        self.assertIn(exc.error_code,
                      ('INSUFFICIENT_CREDITS', 'PROVIDER_CREDITS_EXHAUSTED'))
        self.assertIn('رصيد', str(exc))

    def test_extract_chat_content_still_raises_plain_for_other_errors(self):
        module = self.application_module
        data = self._chat_call({'error': {'message': 'model not found'}}, 404)
        with self.assertRaises(Exception) as ctx:
            module.extract_chat_content(data, 'TEST')
        self.assertIsNot(type(ctx.exception), module.FatalAICallError)

    def test_openrouter_response_message_raises_fatal_for_refusal(self):
        module = self.application_module
        fatal = {'error': {'message': 'wallet', 'fatal': True,
                           'error_code': 'INSUFFICIENT_CREDITS', 'http_status': 402}}
        with self.assertRaises(module.FatalAICallError):
            module.openrouter_response_message(fatal, 'TEST')
        with self.assertRaises(RuntimeError) as ctx:
            module.openrouter_response_message({'error': {'message': 'boom'}}, 'TEST')
        self.assertIsNot(type(ctx.exception), module.FatalAICallError)

    def test_parallel_call_returns_fatal_dict_without_racing_away(self):
        module = self.application_module
        fatal = {'error': {'message': 'wallet', 'fatal': True,
                           'error_code': 'INSUFFICIENT_CREDITS', 'http_status': 402}}
        calls = []
        with patch.object(module, 'call_text_chat', return_value=fatal) as call:
            result = module.call_text_chat_parallel('sys', 'hi', attempts=2)
        calls.append(call.call_count)
        self.assertIs(result, fatal)

    # ── HTTP response mapping ──────────────────────────────────────────

    def test_fatal_http_response_maps_exception_and_dict(self):
        module = self.application_module
        with self.app.app_context():
            exc = module.FatalAICallError(
                module._COMPANY_CREDIT_EXHAUSTED_MSG,
                error_code='INSUFFICIENT_CREDITS', http_status=402)
            response, status = module._ai_fatal_http_response(exc)
            self.assertEqual(status, 402)
            body = response.get_json()
            self.assertEqual(body['error_code'], 'INSUFFICIENT_CREDITS')
            self.assertIn('رصيد', body['error'])

            bare = {'message': module._COMPANY_CREDIT_EXHAUSTED_MSG,
                    'error_code': 'INSUFFICIENT_CREDITS', 'fatal': True,
                    'http_status': 402}
            response, status = module._ai_fatal_http_response(bare)
            self.assertEqual(status, 402)
            self.assertEqual(response.get_json()['error_code'], 'INSUFFICIENT_CREDITS')

            self.assertIsNone(module._ai_fatal_http_response(ValueError('boom')))
            self.assertIsNone(module._ai_fatal_http_response(
                {'error': {'message': 'boom'}}))

    # ── Image API last-error ───────────────────────────────────────────

    def test_images_api_402_records_fatal_last_error(self):
        module = self.application_module
        with self.app.app_context():
            with patch.object(module, '_has_any_openrouter_key', return_value=True), \
                 patch.object(module.requests, 'post',
                              return_value=_FakeResponse(
                                  {'error': {'message': 'Insufficient credits'}}, 402)):
                result = module.call_images_api('prompt', usage_ctx={})
            self.assertIsNone(result)
            err = module.last_images_api_error()
            self.assertIsInstance(err, dict)
            self.assertTrue(err.get('fatal'))
            fatal = module._ai_fatal_http_response(err)
            self.assertIsNotNone(fatal)
            response, status = fatal
            self.assertIn(response.get_json()['error_code'],
                          ('INSUFFICIENT_CREDITS', 'PROVIDER_CREDITS_EXHAUSTED'))
            self.assertIn('رصيد', response.get_json()['error'])

    # ── Slide engine abort ─────────────────────────────────────────────

    def test_slide_engine_aborts_on_fatal_instead_of_fallback(self):
        calls = []

        def call_text_fn(sys_prompt, user_msg, max_tokens=6000):
            calls.append(1)
            return {'error': {'message': 'wallet empty', 'fatal': True,
                              'error_code': 'INSUFFICIENT_CREDITS',
                              'http_status': 402}}

        with self.assertRaises(slide_engine.FatalSlideGenerationError) as ctx:
            slide_engine.generate_single_slide(
                'sys', {'type': 'content', 'title': 'اختبار'}, 1, 2, {},
                call_text_fn, max_retries=5, project_data={})
        self.assertEqual(ctx.exception.error_code, 'INSUFFICIENT_CREDITS')
        self.assertTrue(ctx.exception.fatal_ai_error)
        # Fatal means stop now — the retries that ran before must not repeat.
        self.assertEqual(len(calls), 1)

    def test_slide_engine_retries_generic_failures_then_falls_back(self):
        calls = []

        def call_text_fn(sys_prompt, user_msg, max_tokens=6000):
            calls.append(1)
            return {'error': {'message': 'model not found'}}

        html = slide_engine.generate_single_slide(
            'sys', {'type': 'content', 'title': 'اختبار'}, 1, 2, {},
            call_text_fn, max_retries=1, project_data={})
        # Generic failures retry and then degrade to the deterministic
        # fallback or an empty result — they must not raise as fatal.
        self.assertGreater(len(calls), 1)
        self.assertIn(html, (None, ''))

    # ── Background job failure body ────────────────────────────────────

    def test_slide_job_failure_keeps_billing_reason(self):
        module = self.application_module
        job_id = 'fataljob1'
        with patch.object(
                module, 'api_generate_slide_single',
                side_effect=module.FatalAICallError(
                    module._COMPANY_CREDIT_EXHAUSTED_MSG,
                    error_code='INSUFFICIENT_CREDITS', http_status=402)):
            module._run_slide_generation_job(
                module.app, self.tenant_id, {}, job_id, 'Bearer test')
        job = module._read_job('.slide_jobs', self.tenant_id, job_id)
        self.assertIsInstance(job, dict)
        self.assertEqual(job.get('status'), 'failed')
        self.assertFalse(job.get('success'))
        self.assertIn('رصيد', job.get('error') or '')
        self.assertEqual(job.get('error_code'), 'INSUFFICIENT_CREDITS')
        self.assertEqual(job.get('failureReason'), 'billing_refused')

    # ── Wiring assertions ──────────────────────────────────────────────

    def test_fatal_helper_part_exists_with_expected_surface(self):
        source = (ROOT / 'app_parts' / '01b_ai_error_handling.py').read_text(encoding='utf-8')
        for name in ('class FatalAICallError', '_FATAL_AI_ERROR_CODES',
                     '_provider_credit_error_dict', '_ai_fatal_http_response',
                     'last_images_api_error', '_chat_affordable_tokens'):
            self.assertIn(name, source)

    def test_frontend_keeps_fatal_codes_and_settles_with_real_error(self):
        regen = (ROOT / 'assets' / 'js' / '14-slides-gen' / '03_slide_regeneration.js').read_text(encoding='utf-8')
        self.assertIn('TENANT_GENERATION_FATAL_CODES', regen)
        self.assertIn('INSUFFICIENT_BALANCE', regen)
        media = (ROOT / 'assets' / 'js' / '12-files-media' / '01_files_media.js').read_text(encoding='utf-8')
        self.assertIn("settleGenerationRun(false, planResponse.error ||", media)
        generation = (ROOT / 'assets' / 'js' / '13-visual' / '03_tenant_slide_generation.js').read_text(encoding='utf-8')
        self.assertIn('settleGenerationRun(false, (generationFailure', generation)


if __name__ == '__main__':
    unittest.main()
