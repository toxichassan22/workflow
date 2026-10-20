"""Run control — the stop button's foundation.

The registry is the only thing that stands between a user who noticed the
wrong prompt halfway through a paid generation and the rest of the bill. These
tests never call a provider: HTTP is always patched, so every assertion is
about this repository's own behaviour — that a cancelled run never reaches the
provider, that a cancelled stream is cut instead of run to the end, and that
one company can never stop another company's run.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db
import run_control


class _FakeStreamResponse:
    """A provider stream the test can interrupt."""

    def __init__(self, lines, on_first_line=None):
        self._lines = list(lines)
        self._on_first_line = on_first_line
        self.status_code = 200
        self.encoding = 'utf-8'
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        for index, line in enumerate(self._lines):
            yield line
            if index == 0 and self._on_first_line:
                # The stop arrives after the first chunk reached the caller.
                self._on_first_line()

    def close(self):
        self.closed = True

    def json(self):
        return {}


def _sse(text):
    return 'data: ' + '{"choices":[{"delta":{"content":"' + text + '"}}]}'


class RunControlRegistryTests(unittest.TestCase):
    """The marker file itself."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_provider = run_control._ROOT_PROVIDER
        run_control.set_root_provider(lambda: os.path.join(self.temp_dir.name, 'cancel'))
        self.tenant = 'tenant-run-control'
        self.run_id = 'run-control-0001'

    def tearDown(self):
        run_control.set_root_provider(self.previous_provider)
        self.temp_dir.cleanup()

    def test_a_cancel_is_scoped_to_its_own_tenant(self):
        self.assertTrue(run_control.cancel_run(self.run_id, self.tenant))
        self.assertTrue(run_control.is_run_cancelled(self.run_id, self.tenant))
        self.assertFalse(run_control.is_run_cancelled(self.run_id, 'another-tenant'))

    def test_a_run_id_that_could_escape_the_registry_is_refused(self):
        for hostile in ('../../etc/passwd', 'a/b', 'short', 'run id with spaces'):
            self.assertIsNone(run_control.cancel_path(hostile, self.tenant), hostile)
            self.assertFalse(run_control.cancel_run(hostile, self.tenant), hostile)

    def test_a_tenant_id_that_could_escape_the_registry_is_refused(self):
        self.assertIsNone(run_control.cancel_path(self.run_id, '../../other'))
        self.assertFalse(run_control.cancel_run(self.run_id, '../other'))

    def test_clearing_a_cancel_makes_the_run_live_again(self):
        run_control.cancel_run(self.run_id, self.tenant)
        self.assertTrue(run_control.clear_run_cancel(self.run_id, self.tenant))
        self.assertFalse(run_control.is_run_cancelled(self.run_id, self.tenant))

    def test_a_bound_run_is_what_the_thread_checks(self):
        run_control.bind_run(self.run_id, self.tenant)
        try:
            self.assertFalse(run_control.current_run_cancelled())
            self.assertEqual(run_control.current_run(), (self.run_id, self.tenant))
            run_control.cancel_run(self.run_id, self.tenant)
            self.assertTrue(run_control.current_run_cancelled())
            self.assertTrue(run_control.run_is_cancelled())
        finally:
            run_control.unbind_run()
        self.assertEqual(run_control.current_run(), (None, None))
        self.assertFalse(run_control.current_run_cancelled())

    def test_a_run_bound_to_one_thread_does_not_leak_into_another(self):
        run_control.bind_run(self.run_id, self.tenant)
        try:
            seen = {}

            def worker():
                seen['cancelled'] = run_control.run_is_cancelled()

            import threading
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            self.assertFalse(seen['cancelled'])
        finally:
            run_control.unbind_run()


class RunControlAiLayerTests(unittest.TestCase):
    """A cancelled run must never cost a token."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_provider = run_control._ROOT_PROVIDER
        run_control.set_root_provider(lambda: os.path.join(self.temp_dir.name, 'cancel'))
        self.tenant = 'tenant-ai-layer'
        self.run_id = 'ai-layer-run-0001'

    def tearDown(self):
        run_control.set_root_provider(self.previous_provider)
        self.temp_dir.cleanup()

    def _application(self):
        import app as application_module
        return application_module

    def _usage_ctx(self, application_module):
        return run_control.attach_run(
            {'tenant_id': self.tenant, 'flow': 'slide'}, self.run_id, self.tenant)

    def test_a_cancelled_text_call_never_reaches_the_provider(self):
        application_module = self._application()
        run_control.cancel_run(self.run_id, self.tenant)
        called = []

        def fake_post(*args, **kwargs):
            called.append(args)
            raise AssertionError('the provider must not be called for a cancelled run')

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post):
            result = application_module.call_openrouter_chat(
                'system', 'user', usage_ctx=self._usage_ctx(application_module))
        self.assertEqual(called, [])
        self.assertTrue(result.get('cancelled'))
        self.assertEqual(result.get('error_code'), run_control.CANCELLED_ERROR_CODE)

    def test_a_live_text_call_still_reaches_the_provider(self):
        application_module = self._application()

        class _Response:
            status_code = 200
            encoding = 'utf-8'
            text = '{"choices":[{"message":{"content":"ok"}}]}'

            def json(self):
                return {'choices': [{'message': {'content': 'ok'}}]}

        called = []

        def fake_post(*args, **kwargs):
            called.append(args)
            return _Response()

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post):
            result = application_module.call_openrouter_chat(
                'system', 'user', usage_ctx=self._usage_ctx(application_module))
        self.assertEqual(len(called), 1)
        self.assertNotIn('cancelled', result)

    def test_a_cancelled_image_call_never_reaches_the_provider(self):
        application_module = self._application()
        run_control.cancel_run(self.run_id, self.tenant)
        called = []

        def fake_post(*args, **kwargs):
            called.append(args)
            raise AssertionError('the provider must not be called for a cancelled run')

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post):
            image = application_module.call_images_api(
                'a picture', usage_ctx=self._usage_ctx(application_module))
        self.assertEqual(called, [])
        self.assertIsNone(image)
        error = application_module.last_images_api_error() or {}
        self.assertEqual(error.get('error_code'), run_control.CANCELLED_ERROR_CODE)
        self.assertTrue(error.get('cancelled'))

    def test_a_cancelled_stream_is_cut_instead_of_run_to_the_end(self):
        application_module = self._application()
        response = _FakeStreamResponse(
            [_sse('أول'), _sse('ثاني'), _sse('ثالث')],
            on_first_line=lambda: run_control.cancel_run(self.run_id, self.tenant),
        )

        def fake_post(*args, **kwargs):
            return response

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post), \
                patch.object(run_control, 'CANCEL_CHECK_INTERVAL', 0):
            result = application_module.call_openrouter_chat_stream(
                'system', 'user', usage_ctx=self._usage_ctx(application_module))
        self.assertTrue(result.get('cancelled'))
        self.assertEqual(result.get('error_code'), run_control.CANCELLED_ERROR_CODE)
        self.assertTrue(response.closed, 'the provider connection must be closed')
        self.assertEqual(result.get('partial'), 'أول')

    def test_a_cancelled_agent_planner_never_reaches_the_provider(self):
        """The agent planner is one of the most expensive calls in the product."""
        application_module = self._application()
        run_control.cancel_run(self.run_id, self.tenant)

        def fake_post(*args, **kwargs):
            raise AssertionError('the provider must not be called for a cancelled run')

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post):
            response = application_module.call_openrouter_messages(
                [{'role': 'user', 'content': 'خطة'}],
                usage_ctx=self._usage_ctx(application_module))
        self.assertTrue(response.get('cancelled'), response)
        self.assertEqual(response.get('error_code'), run_control.CANCELLED_ERROR_CODE)

    def test_a_live_stream_returns_its_text(self):
        application_module = self._application()
        response = _FakeStreamResponse([_sse('نص '), _sse('كامل'), 'data: [DONE]'])

        def fake_post(*args, **kwargs):
            return response

        with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                patch.object(application_module.requests, 'post', side_effect=fake_post):
            result = application_module.call_openrouter_chat_stream(
                'system', 'user', usage_ctx=self._usage_ctx(application_module))
        self.assertNotIn('cancelled', result)
        self.assertEqual(result['choices'][0]['message']['content'], 'نص كامل')


class RunControlRouteTests(unittest.TestCase):
    """The endpoint the client presses."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'run-control.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Run Control Co', 'rc@example.test', 'hash', 'run-control-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'rc@example.test', user_id=None, user_name='RC Admin',
            user_role='company_admin',
        )
        cls.previous_provider = run_control._ROOT_PROVIDER

    @classmethod
    def tearDownClass(cls):
        run_control.set_root_provider(cls.previous_provider)
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def setUp(self):
        self.run_id = 'route-run-0001'

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def test_the_stop_endpoint_marks_the_run(self):
        client = self.app.test_client()
        response = client.post(f'/api/runs/{self.run_id}/cancel', headers=self._headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body.get('success'))
        self.assertTrue(body.get('cancelRequested'))
        self.assertTrue(run_control.is_run_cancelled(self.run_id, self.tenant_id))

    def test_the_stop_endpoint_reports_the_run_status(self):
        client = self.app.test_client()
        client.post(f'/api/runs/{self.run_id}/cancel', headers=self._headers())
        response = client.get(f'/api/runs/{self.run_id}', headers=self._headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json().get('cancelled'))

    def test_the_stop_endpoint_rejects_an_unusable_run_id(self):
        client = self.app.test_client()
        for hostile in ('short', 'run.id', 'run%20id'):
            response = client.post(f'/api/runs/{hostile}/cancel', headers=self._headers())
            self.assertEqual(response.status_code, 400, hostile)
            self.assertEqual(response.get_json().get('error_code'), 'RUN_INVALID', hostile)

    def test_the_stop_endpoint_needs_a_token(self):
        client = self.app.test_client()
        response = client.post(f'/api/runs/{self.run_id}/cancel')
        self.assertEqual(response.status_code, 401)

    def test_a_run_of_another_company_cannot_be_stopped_from_here(self):
        with self.app.app_context():
            other_tenant = db.create_tenant('Other Co', 'other@example.test', 'hash', 'other-co')
        client = self.app.test_client()
        response = client.post(f'/api/runs/{self.run_id}/cancel', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(run_control.is_run_cancelled(self.run_id, other_tenant))

    def test_a_cancelled_slide_request_never_reaches_the_provider(self):
        """The slide that was stopped must not become a paid call."""
        application_module = self.application_module
        run_id = 'slide-stop-run-0001'
        run_control.cancel_run(run_id, self.tenant_id)
        run_control.bind_run(run_id, self.tenant_id)

        def fake_post(*args, **kwargs):
            raise AssertionError('the provider must not be called for a cancelled run')

        client = self.app.test_client()
        try:
            with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                    patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                    patch.object(application_module, '_require_billing_balance', return_value=None), \
                    patch.object(application_module.requests, 'post', side_effect=fake_post):
                response = client.post('/api/generate-slide-single', headers=self._headers(), json={
                    'projectData': {'project_name': 'مشروع الاختبار'},
                    'slidePlan': {'slides': [{'title': 'شريحة محتوى', 'type': 'content'}]},
                })
        finally:
            run_control.unbind_run()
        body = response.get_json()
        self.assertEqual(response.status_code, 409, body)
        self.assertEqual(body.get('error_code'), run_control.CANCELLED_ERROR_CODE)
        self.assertNotIn('slide', body)


class RunControlJobTests(unittest.TestCase):
    """The queued flows: the site analysis and the visual-concept image."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'run-control-jobs.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Run Jobs Co', 'jobs@example.test', 'hash', 'run-jobs-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'jobs@example.test', user_id=None, user_name='Jobs Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def test_the_site_analysis_queues_a_job_the_stop_button_can_reach(self):
        application_module = self.application_module
        client = self.app.test_client()
        with patch.object(application_module.maps_service, 'extract_coords_from_maps_link',
                          return_value={'lat': 25.1, 'lng': 47.6}), \
                patch.object(application_module, '_collect_site_fields',
                             return_value=({'location_lat': 25.1}, [], [], [], [], [], None, {})):
            response = client.post('/api/analyze-site', headers=self._headers(), json={
                'projectData': {'location_address': 'https://www.google.com/maps/@25.1,47.6,17z'},
                'generateMaps': False,
                'background': True,
            })
            self.assertEqual(response.status_code, 202, response.get_json())
            job_id = str(response.get_json().get('jobId') or '')
            self.assertTrue(job_id, response.get_json())
            # The job settles inside the patch, so the sweep never reaches the
            # real Maps provider.
            deadline = time.time() + 15
            job = None
            while time.time() < deadline:
                job = application_module._read_job('.site_analysis_jobs', self.tenant_id, job_id)
                if job and job.get('status') in ('completed', 'failed', 'cancelled'):
                    break
                time.sleep(0.1)
        self.assertIsNotNone(job, 'the site analysis job never settled')
        self.assertEqual(job.get('status'), 'completed', job)
        # The handle is a run: the stop button can cancel it.
        self.assertTrue(run_control.cancel_run(job_id, self.tenant_id))
        self.assertTrue(run_control.is_run_cancelled(job_id, self.tenant_id))

    def test_a_cancelled_visual_concept_image_never_reaches_the_provider(self):
        application_module = self.application_module
        run_id = 'vc-image-run-0001'
        run_control.cancel_run(run_id, self.tenant_id)
        run_control.bind_run(run_id, self.tenant_id)

        def fake_post(*args, **kwargs):
            raise AssertionError('the provider must not be called for a cancelled run')

        try:
            with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                    patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                    patch.object(application_module, '_visual_concept_request_bundle',
                                 return_value=({}, {'idea': 'فكرة'}, [])), \
                    patch.object(application_module, '_visual_concept_cover_image', return_value=''), \
                    patch.object(application_module, '_visual_concept_collect_generation_references',
                                 return_value=[]), \
                    patch.object(application_module, '_visual_concept_attach_style_reference_suffix',
                                 return_value='وصف الصورة'), \
                    patch.object(application_module.requests, 'post', side_effect=fake_post):
                with self.app.app_context():
                    result, status = application_module._visual_concept_generate_image_result(
                        {'slotId': 'cover', 'prompt': 'وصف الصورة'}, 'cover')
        finally:
            run_control.unbind_run()
        self.assertFalse(result.get('success'), result)
        self.assertEqual(result.get('error_code'), run_control.CANCELLED_ERROR_CODE)

    def test_a_cancelled_visual_concept_chat_never_reaches_the_provider(self):
        application_module = self.application_module
        run_id = 'vc-chat-run-0001'
        run_control.cancel_run(run_id, self.tenant_id)
        run_control.bind_run(run_id, self.tenant_id)

        def fake_post(*args, **kwargs):
            raise AssertionError('the provider must not be called for a cancelled run')

        try:
            with patch.object(application_module, '_tenant_key_gate', return_value=None), \
                    patch.object(application_module, '_has_any_openrouter_key', return_value=True), \
                    patch.object(application_module, '_visual_concept_request_bundle',
                                 return_value=({}, {'idea': 'فكرة'}, [])), \
                    patch.object(application_module, '_visual_concept_cover_image', return_value=''), \
                    patch.object(application_module, '_visual_concept_collect_generation_references',
                                 return_value=[]), \
                    patch.object(application_module, '_visual_concept_edit_reference_uris',
                                 return_value=[]), \
                    patch.object(application_module, '_visual_concept_generate_prompt_text',
                                 side_effect=AssertionError('the provider must not be called')), \
                    patch.object(application_module.requests, 'post', side_effect=fake_post):
                result, status = application_module._visual_concept_chat_result(
                    {'slotId': 'cover', 'message': 'اجعلها ليلية'}, 'cover')
        finally:
            run_control.unbind_run()
        self.assertFalse(result.get('success'), result)


def _frontend_text(application_module):
    """The full client source: shell + styles + scripts in load order."""
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    for css in sorted((ROOT / 'assets' / 'css').rglob('*.css')):
        parts.append(css.read_text(encoding='utf-8'))
    for name in application_module.FRONTEND_JS_ORDER:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


class RunControlClientTests(unittest.TestCase):
    """The stop button must exist and must reach the server."""

    @classmethod
    def setUpClass(cls):
        import app as application_module
        cls.application_module = application_module
        cls.source = _frontend_text(application_module)
        cls.shell = (ROOT / 'index.html').read_text(encoding='utf-8')

    def test_the_banner_and_the_loader_carry_a_stop_button(self):
        self.assertIn('id="liveGenStopButton"', self.shell)
        self.assertIn('id="globalLoaderStopButton"', self.shell)
        self.assertIn('stopTenantGeneration()', self.shell)

    def test_the_stop_button_asks_the_server_to_stop_the_runs(self):
        self.assertIn('/api/runs/', self.source)
        self.assertIn('cancelTenantGenerationRun', self.source)

    def test_the_slide_loop_registers_its_run_so_the_stop_reaches_it(self):
        self.assertIn('registerTenantGenerationRun', self.source)
        self.assertIn('releaseTenantGenerationRun', self.source)

    def test_a_stopped_run_never_launches_another_slide(self):
        self.assertIn('tenantGenerationStopRequested', self.source)

    def test_the_stop_button_carries_no_icon_glyph(self):
        import re
        for marker in ('liveGenStopButton', 'globalLoaderStopButton'):
            match = re.search(r'<button[^>]*id="' + marker + r'"[^>]*>.*?</button>',
                              self.shell, re.S)
            self.assertIsNotNone(match, marker)
            snippet = match.group(0)
            for glyph in ('→', '←', '↑', '↓', '✕', '×', '⏹', '■', '✔', '✓', '⚠', '⏸'):
                self.assertNotIn(glyph, snippet, f'{marker} carries an icon glyph')


if __name__ == '__main__':
    unittest.main()
