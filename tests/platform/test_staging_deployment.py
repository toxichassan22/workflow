import ast
import importlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml
from flask import Flask, jsonify, request

import staging_deploy_runtime


ROOT = Path(__file__).resolve().parents[2]


def load_app_parts(root, application):
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    start = next(index for index, node in enumerate(tree.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == '_PARTS_DIR'
                         for target in node.targets))
    runtime = (importlib.import_module('staging_deploy_runtime')
               if importlib.util.find_spec('staging_deploy_runtime') else None)
    scope = {'__file__': str(root / 'app.py'), 'os': os, 'app': application,
             'staging_deploy_runtime': runtime}
    exec(compile(ast.Module(body=tree.body[start:], type_ignores=[]), 'app.py', 'exec'), scope)
    return scope


class StagingDeploymentRegressionTests(unittest.TestCase):
    def test_gunicorn_preloads_the_app_before_starting_workers(self):
        for name in ('start_server-staging.sh', 'start_server.sh'):
            source = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('--preload', source, name)

    def test_old_flat_copy_does_not_register_the_endpoint_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parts = root / 'app_parts'
            grouped = parts / '01_ai'
            grouped.mkdir(parents=True)
            route = "@app.route('/api/ai-usage')\ndef api_ai_usage():\n    return {!r}\n"
            (parts / '02_ai_usage_metering.py').write_text(route.format('legacy'), encoding='utf-8')
            (grouped / '02_ai_usage_metering.py').write_text(route.format('current'), encoding='utf-8')
            application = Flask('staging-loader-regression')
            load_app_parts(root, application)
            self.assertEqual(application.test_client().get('/api/ai-usage').get_data(as_text=True), 'current')
            self.assertEqual(len(list(application.url_map.iter_rules('api_ai_usage'))), 1)

    def test_workflow_does_not_retry_deployment_or_verification(self):
        workflow = (ROOT / '.github/workflows/deploy-staging.yml').read_text(encoding='utf-8')
        self.assertNotIn('--retry', workflow)
        self.assertNotIn('seq 1 72', workflow)
        self.assertNotIn('seq 1 12', workflow)

    def test_required_dependency_errors_are_not_ignored(self):
        script = (ROOT / 'deploy-staging.sh').read_text(encoding='utf-8')
        self.assertNotRegex(script, r'"\$PIP" install[^\n]*\|\| true')

    def test_slide_vision_probe_loads_moved_modules_without_pythonpath(self):
        script = (ROOT / 'deploy-staging.sh').read_text(encoding='utf-8')
        probe = script.split('<<PY\n', 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            app_dir = Path(folder) / 'staging app'
            scripts = app_dir / 'scripts'
            scripts.mkdir(parents=True)
            (scripts / '_bootstrap.py').write_text(
                (ROOT / 'scripts/_bootstrap.py').read_text(encoding='utf-8'), encoding='utf-8')
            pdf = app_dir / 'modules/pdf'
            playwright = pdf / 'playwright'
            playwright.mkdir(parents=True)
            (pdf / 'generate_pdf_from_preview.py').write_text(
                "def _launch_chromium(p):\n    return p.browser, 'fixture'\n", encoding='utf-8')
            (playwright / '__init__.py').write_text('', encoding='utf-8')
            (playwright / 'sync_api.py').write_text(
                "class Browser:\n    version = 'fake-chromium'\n    def close(self): pass\n"
                "class Playwright:\n    browser = Browser()\n"
                "    def __enter__(self): return self\n    def __exit__(self, *args): pass\n"
                "def sync_playwright(): return Playwright()\n", encoding='utf-8')
            install_log = app_dir / 'install.log'
            install_log.write_text('fixture install completed', encoding='utf-8')
            probe = probe.replace('$install_log', install_log.as_posix())
            result = subprocess.run([sys.executable, '-I', '-', str(scripts)], input=probe,
                                    cwd=folder, text=True, capture_output=True, check=True)
            payload = json.loads(result.stdout)
            self.assertTrue(payload['available'], payload)
            self.assertEqual(payload['error'], 'chromium fake-chromium via fixture')
            self.assertEqual(payload['installLog'], 'fixture install completed')


class StagingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_file(self, name, text='code'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_initial_upgrade_archives_old_flat_parts_without_touching_data(self):
        old = self.write_file('app_parts/02_usage.py', 'legacy')
        current = self.write_file('app_parts/01_ai/02_usage.py', 'current')
        self.write_file('.deployed_commit', json.dumps({'source': 'github-staging'}))
        data = {name: self.write_file(name, 'owner data')
                for name in ('app.db', '.env', 'uploads/customer.py', 'outputs/proposal.pdf')}
        selected = staging_deploy_runtime.app_part_paths(self.root / 'app_parts')
        self.assertEqual(selected, [str(current)])
        self.assertFalse(old.exists())
        backups = list((self.root / '.deploy_backups').rglob('02_usage.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'), 'legacy')
        for path in data.values():
            self.assertEqual(path.read_text(encoding='utf-8'), 'owner data')

    def test_two_grouped_copies_are_not_silently_accepted(self):
        self.write_file('app_parts/01_ai/02_usage.py')
        self.write_file('app_parts/02_platform/02_usage.py')
        with self.assertRaisesRegex(ValueError, 'Duplicate grouped app part'):
            staging_deploy_runtime.app_part_paths(self.root / 'app_parts')

    def test_flat_only_parts_remain_supported(self):
        old = self.write_file('app_parts/02_usage.py')
        self.assertEqual(staging_deploy_runtime.app_part_paths(self.root / 'app_parts'), [str(old)])

    def test_runtime_cleanup_preserves_customer_files_and_untracked_code(self):
        current = {'app.py', 'app_parts/01_ai/02_usage.py', 'modules/db/db.py'}
        previous = {'app.py', 'app_parts/02_usage.py', 'db.py', 'db_parts/01_schema.py',
                    'app.db', '.env', 'uploads/customer.py'}
        self.write_file('.deployed_commit', json.dumps({'commit': 'a' * 40}))
        for name in current | previous | {'app_parts/local_override.py', 'venv/local.py'}:
            self.write_file(name, name)
        with patch.object(staging_deploy_runtime, '_tracked_files', side_effect=(current, previous)):
            archived = staging_deploy_runtime.prepare_runtime('repo', self.root)
        self.assertEqual(set(archived), {'app_parts/02_usage.py', 'db.py', 'db_parts/01_schema.py'})
        for name in current | {'app.db', '.env', 'uploads/customer.py',
                               'app_parts/local_override.py', 'venv/local.py'}:
            self.assertEqual((self.root / name).read_text(encoding='utf-8'), name)
        self.assertEqual(set(json.loads((self.root / '.deploy_inventory.json').read_text())['files']), current)

    def test_git_inventory_reads_the_real_repository_without_mutating_it(self):
        files = staging_deploy_runtime._tracked_files(ROOT, 'HEAD', required=True)
        self.assertIn('app.py', files)
        self.assertIn('modules/db/db.py', files)
        self.assertNotIn('app.db', files)

    def test_inventory_remembers_code_from_a_failed_previous_sync(self):
        self.write_file('.deploy_inventory.json', json.dumps({'files': ['app_parts/01_ai/old.py']}))
        self.write_file('app_parts/01_ai/old.py', 'failed deployment code')
        with patch.object(staging_deploy_runtime, '_tracked_files', return_value={'app.py'}):
            archived = staging_deploy_runtime.prepare_runtime('repo', self.root)
        self.assertEqual(archived, ['app_parts/01_ai/old.py'])

    def test_path_traversal_and_protected_code_are_never_archived(self):
        data = self.write_file('uploads/customer.py', 'customer')
        self.assertEqual(staging_deploy_runtime.archive_code(
            self.root, ['../outside.py', '/absolute.py', 'C:/outside.py', 'uploads/customer.py']), [])
        self.assertEqual(data.read_text(), 'customer')

    def test_failure_summary_redacts_secrets_and_retains_the_exception(self):
        text = ('Traceback\nAssertionError: api_ai_usage provider-secret-value '
                'https://provider.test/?key=hidden\n[CONFIG] Primary model: model-name')
        result = staging_deploy_runtime.sanitize_error(text, {'OPENROUTER_KEY': 'provider-secret-value'})
        self.assertIn('AssertionError: api_ai_usage', result)
        self.assertNotIn('provider-secret-value', result)
        self.assertNotIn('hidden', result)
        self.assertNotIn('[CONFIG]', result)

    def test_unknown_bearer_keys_and_password_fields_are_redacted(self):
        result = staging_deploy_runtime.sanitize_error(
            'RuntimeError: Bearer unknown-token password="private password" '
            'api_key=unlisted-key sk-or-v1-abcdefghijklmnop', {})
        for value in ('unknown-token', 'private password', 'unlisted-key', 'abcdefghijklmnop'):
            self.assertNotIn(value, result)

    def test_request_claim_is_atomic_across_concurrent_callers(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: staging_deploy_runtime.claim_request(self.root, 'run-1'),
                                       range(16)))
        self.assertEqual(sum(results), 1)

    def test_status_records_each_request_and_its_failed_step(self):
        first = staging_deploy_runtime.write_status(self.root, 'a' * 40, 'queued', 'start', request_id='run-1')
        running = staging_deploy_runtime.write_status(self.root, 'a' * 40, 'running', 'migrate', request_id='run-1')
        failed = staging_deploy_runtime.write_status(self.root, 'a' * 40, 'failed', 'migrate',
                                                    1, 'run-1', error='AssertionError: api_ai_usage')
        staging_deploy_runtime.write_status(self.root, 'b' * 40, 'running', 'sync', request_id='run-2')
        self.assertEqual(first['started_at'], running['started_at'])
        self.assertEqual(first['started_at'], failed['started_at'])
        self.assertEqual(staging_deploy_runtime.read_status(self.root, 'run-1'), failed)
        self.assertEqual(staging_deploy_runtime.read_status(self.root)['request_id'], 'run-2')
        self.assertEqual(failed['exit_code'], 1)
        self.assertEqual(failed['error'], 'AssertionError: api_ai_usage')
        self.assertIsNotNone(failed['finished_at'])
        self.assertIsNone(running['finished_at'])

    def test_step_log_extracts_the_traceback_instead_of_later_config_lines(self):
        log = self.write_file('step.log', 'Traceback\nModuleNotFoundError: missing_module\n[CONFIG] enabled\n')
        result = staging_deploy_runtime.write_status(self.root, 'a' * 40, 'failed', 'migrate',
                                                    1, 'run-1', log_path=log)
        self.assertEqual(result['error'], 'ModuleNotFoundError: missing_module')

    def test_invalid_request_id_cannot_select_a_status_file(self):
        with self.assertRaisesRegex(ValueError, 'Invalid deployment request ID'):
            staging_deploy_runtime.read_status(self.root, '../outside')


class StagingWebhookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'deploy-staging.sh').write_text('exit 0', encoding='utf-8')
        environment = patch.dict(os.environ, {'STAGING_APP_DIR': str(self.root),
                                               'DEPLOY_WEBHOOK_SECRET': 'test-deploy-secret',
                                               'DEPLOY_WEBHOOK_SECRET_STAGING': ''})
        environment.start()
        self.addCleanup(environment.stop)
        self.application = Flask('staging-webhook-tests')
        self.application.config['TESTING'] = True
        self.scope = {'app': self.application, 'os': os, 're': re, 'secrets': secrets,
                      '_uuid': uuid, 'request': request, 'jsonify': jsonify,
                      'staging_deploy_runtime': staging_deploy_runtime,
                      'DEPLOYMENT_MARKER_PATH': str(self.root / '.deployed_commit'),
                      'db': SimpleNamespace(_utcnow=lambda: datetime(2026, 10, 12, 16, 0))}
        source = ROOT / 'app_parts/22_rules_pages/22b_staging_deployment.py'
        exec(compile(source.read_text(encoding='utf-8'), str(source), 'exec'), self.scope)
        self.client = self.application.test_client()
        self.headers = {'X-Deploy-Secret': 'test-deploy-secret', 'X-Deploy-Request-ID': 'run-1'}
        self.commit = 'a' * 40

    def test_webhook_spawns_once_and_records_the_request_before_returning(self):
        with patch('subprocess.Popen') as spawn:
            response = self.client.post('/api/deploy-webhook-staging?commit=' + self.commit,
                                        headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[0], ['bash', str(self.root / 'deploy-staging.sh'), self.commit])
        self.assertEqual(spawn.call_args.kwargs['env']['STAGING_DEPLOY_REQUEST_ID'], 'run-1')
        status = staging_deploy_runtime.read_status(self.root, 'run-1')
        self.assertEqual(status['status'], 'queued')
        self.assertEqual(response.get_json()['request_id'], 'run-1')

    def test_repeated_request_id_does_not_start_another_deployment(self):
        with patch('subprocess.Popen') as spawn:
            first = self.client.post('/api/deploy-webhook-staging?commit=' + self.commit, headers=self.headers)
            duplicate = self.client.post('/api/deploy-webhook-staging?commit=' + self.commit, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(spawn.call_count, 1)

    def test_invalid_commit_or_request_id_never_spawns(self):
        with patch('subprocess.Popen') as spawn:
            invalid_commit = self.client.post('/api/deploy-webhook-staging?commit=invalid', headers=self.headers)
            invalid_id = self.client.post('/api/deploy-webhook-staging?commit=' + self.commit,
                                          headers=dict(self.headers, **{'X-Deploy-Request-ID': '../outside'}))
        self.assertEqual(invalid_commit.status_code, 400)
        self.assertEqual(invalid_id.status_code, 400)
        spawn.assert_not_called()

    def test_request_status_requires_the_deployment_secret(self):
        staging_deploy_runtime.write_status(self.root, self.commit, 'failed', 'migrate',
                                            1, 'run-1', error='AssertionError: api_ai_usage')
        public = self.client.get('/api/deploy-status-staging/run-1')
        private = self.client.get('/api/deploy-status-staging/run-1', headers=self.headers)
        self.assertEqual(public.status_code, 401)
        self.assertEqual(private.status_code, 200)
        self.assertEqual(private.get_json()['error'], 'AssertionError: api_ai_usage')
        self.assertEqual(private.headers['Cache-Control'], 'no-store')

    def test_public_health_metadata_never_includes_the_error_detail(self):
        staging_deploy_runtime.write_status(self.root, self.commit, 'failed', 'migrate',
                                            1, 'run-1', error='AssertionError: internal detail')
        with self.application.test_request_context('/health'):
            public = self.scope['_read_deploy_status']()
        self.assertEqual(public['status'], 'failed')
        self.assertNotIn('error', public)
        self.assertNotIn('request_id', public)

    def test_spawn_error_is_recorded_and_redacted(self):
        with patch.dict(os.environ, {'OPENROUTER_KEY': 'provider-secret-value'}), \
                patch('subprocess.Popen', side_effect=OSError('cannot spawn provider-secret-value')):
            response = self.client.post('/api/deploy-webhook-staging?commit=' + self.commit,
                                        headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('provider-secret-value', response.get_data(as_text=True))
        self.assertEqual(staging_deploy_runtime.read_status(self.root, 'run-1')['status'], 'failed')


class StagingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT / '.github/workflows/deploy-staging.yml').read_text(encoding='utf-8'))
        step = next(step for step in cls.workflow['jobs']['deploy-staging']['steps']
                    if step['name'].startswith('Await Deployment'))
        source = step['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        cls.scope = {'__name__': 'staging_workflow_tests'}
        exec(compile(source, 'deploy-staging.yml', 'exec'), cls.scope)
        cls.commit = 'a' * 40

    def state(self, status, step='migrate', commit=None):
        return {'commit': commit or self.commit, 'request_id': 'run-1', 'status': status,
                'step': step, 'exit_code': 1 if status == 'failed' else 0,
                'error': 'AssertionError: api_ai_usage'}

    def test_first_recorded_failure_stops_without_sleep_or_verification(self):
        fetch = Mock(return_value=self.state('failed'))
        sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, 'failed at migrate.*AssertionError: api_ai_usage'):
            self.scope['wait_for_deployment'](fetch, self.commit, 'run-1', clock=lambda: 0, sleep=sleep)
        fetch.assert_called_once()
        sleep.assert_not_called()

    def test_running_process_is_waited_for_but_failure_is_never_retried(self):
        fetch = Mock(side_effect=[self.state('running'), self.state('failed')])
        sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, 'failed at migrate'):
            self.scope['wait_for_deployment'](fetch, self.commit, 'run-1', clock=lambda: 0, sleep=sleep)
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_success_waits_for_the_recorded_completion_not_just_a_commit_marker(self):
        fetch = Mock(side_effect=[self.state('queued', 'start'), self.state('running'), self.state('deployed', 'restart')])
        sleep = Mock()
        result = self.scope['wait_for_deployment'](fetch, self.commit, 'run-1', clock=lambda: 0, sleep=sleep)
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_queued_process_that_never_starts_fails_without_waiting_the_full_timeout(self):
        clock = Mock(side_effect=[0, 31, 31])
        fetch = Mock(return_value=self.state('queued', 'start'))
        sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, 'did not start the deployment process'):
            self.scope['wait_for_deployment'](fetch, self.commit, 'run-1', clock=clock, sleep=sleep)
        fetch.assert_called_once()
        sleep.assert_not_called()

    def test_successful_commit_verification_is_one_request(self):
        fetch = Mock(return_value={'deployed_commit': self.commit})
        self.scope['verify_commit'](fetch, self.commit)
        fetch.assert_called_once()

    def test_wrong_commit_fails_on_the_single_verification_request(self):
        fetch = Mock(return_value={'deployed_commit': 'b' * 40})
        with self.assertRaisesRegex(RuntimeError, 'Staging verification failed'):
            self.scope['verify_commit'](fetch, self.commit)
        fetch.assert_called_once()

    def test_transport_error_is_not_retried(self):
        fetch = Mock(side_effect=RuntimeError('connection failed'))
        sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, 'connection failed'):
            self.scope['wait_for_deployment'](fetch, self.commit, 'run-1', clock=lambda: 0, sleep=sleep)
        fetch.assert_called_once()
        sleep.assert_not_called()

    def test_other_request_result_is_not_accepted(self):
        result = self.state('deployed')
        result['request_id'] = 'another-run'
        with self.assertRaisesRegex(RuntimeError, 'different request'):
            self.scope['wait_for_deployment'](lambda: result, self.commit, 'run-1', clock=lambda: 0)

    def test_legacy_webhook_upgrade_ignores_an_old_failure_of_the_same_commit(self):
        old = dict(self.state('failed'), finished_at='2026-10-12T15:00:00Z')
        new = dict(self.state('deployed'), finished_at='2026-10-12T16:01:00Z')
        fetch = Mock(side_effect=[{'last_deploy': old}, {'last_deploy': new}])
        sleep = Mock()
        result = self.scope['wait_for_deployment'](fetch, self.commit, triggered_at='2026-10-12T16:00:00',
                                                  clock=lambda: 0, sleep=sleep)
        self.assertEqual(result['status'], 'deployed')
        sleep.assert_called_once()

    def test_pipeline_failure_never_calls_final_verification(self):
        environment = {'STAGING_BASE_URL': 'https://staging.example.test', 'EXPECTED_COMMIT': self.commit,
                       'DEPLOY_WEBHOOK_SECRET': 'test-secret', 'STAGING_DEPLOY_REQUEST_ID': 'run-1'}
        fetch = Mock(return_value=self.state('failed'))
        with patch.dict(os.environ, environment), patch.dict(self.scope, {'fetch_json': fetch}):
            with self.assertRaisesRegex(RuntimeError, 'failed at migrate'):
                self.scope['main']()
        fetch.assert_called_once_with('https://staging.example.test/api/deploy-status-staging/run-1', 'test-secret')

    def test_pipeline_success_verifies_the_live_commit_once(self):
        environment = {'STAGING_BASE_URL': 'https://staging.example.test', 'EXPECTED_COMMIT': self.commit,
                       'DEPLOY_WEBHOOK_SECRET': 'test-secret', 'STAGING_DEPLOY_REQUEST_ID': 'run-1'}
        fetch = Mock(side_effect=[self.state('deployed'), {'deployed_commit': self.commit}])
        with patch.dict(os.environ, environment), patch.dict(self.scope, {'fetch_json': fetch}):
            self.scope['main']()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args.args[0], 'https://staging.example.test/health?deploy_check=' + self.commit)

    def test_staging_jobs_are_serialized_without_cancelling_a_running_deploy(self):
        self.assertEqual(self.workflow['concurrency'], {'group': 'landloom-staging', 'cancel-in-progress': False})

    def test_application_health_error_stops_readiness_after_one_request(self):
        source = (ROOT / 'start_server-staging.sh').read_text(encoding='utf-8')
        readiness = source[source.index('HEALTH_OK=0'):source.index('if [ "$HEALTH_OK" -eq 1 ]; then')]
        stubs = ('NEW_PID=123\nSELECTED_PORT=8002\nHEALTH_PATH=/health\n'
                 'kill() { return 0; }\n'
                 'curl() { printf "500"; printf "curl-called\\n" >&2; }\n'
                 'sleep() { printf "unexpected-sleep\\n"; }\n'
                 'log_readiness_probe() { printf "probe %s\\n" "$1"; }\n'
                 'log() { printf "%s\\n" "$1"; }\n')
        result = subprocess.run(['bash', '-s'], input=stubs + readiness, text=True,
                                capture_output=True, check=True)
        self.assertEqual(result.stderr.count('curl-called'), 1)
        self.assertIn('staging health returned HTTP 500', result.stdout)
        self.assertNotIn('unexpected-sleep', result.stdout)

    def test_staging_readiness_logs_each_probe_result_and_duration(self):
        source = (ROOT / 'start_server-staging.sh').read_text(encoding='utf-8')
        probe_helper = re.search(r'(?ms)^log_readiness_probe\(\) \{\n.*?^\}', source).group(0)
        readiness = source[source.index('HEALTH_OK=0'):source.index('if [ "$HEALTH_OK" -eq 1 ]; then')]
        stubs = ('WATCHDOG_LOG=/dev/null\nNEW_PID=123\nSELECTED_PORT=8002\nHEALTH_PATH=/health\n'
                 'kill() { return 0; }\n'
                 'CURL_STATE="$(mktemp)"\nrm -f "$CURL_STATE"\n'
                 'trap \'rm -f "$CURL_STATE"\' EXIT\n'
                 'curl() { if [ ! -f "$CURL_STATE" ]; then : > "$CURL_STATE"; '
                 'printf "000"; return 7; fi; printf "200"; }\n'
                 'sleep() { :; }\n')
        result = subprocess.run(['bash', '-s'], input=probe_helper + '\n' + stubs + readiness,
                                text=True, capture_output=True, check=True)
        self.assertRegex(result.stdout,
                         r'INFO: staging readiness probe run_pid=\d+ attempt=1 port=8002 '
                         r'gunicorn_pid=123 status=000 curl_exit=7 elapsed_ms=\d+')
        self.assertRegex(result.stdout,
                         r'INFO: staging readiness probe run_pid=\d+ attempt=2 port=8002 '
                         r'gunicorn_pid=123 status=200 curl_exit=0 elapsed_ms=\d+')
        self.assertEqual(result.stdout.count('INFO: staging readiness probe '), 2)

    def test_deploy_steps_log_elapsed_time_and_preserve_exit_status(self):
        source = (ROOT / 'deploy-staging.sh').read_text(encoding='utf-8')
        step_helper = re.search(r'(?ms)^run_deploy_step\(\) \{\n.*?^\}', source).group(0)
        script = ('set -eo pipefail\nSTEP_LOG=/dev/null\nDEPLOY_STEP=\n'
                  'write_deploy_status() { :; }\n' + step_helper + '\n'
                  'run_deploy_step deps requirements bash -c \'printf "pip output\\n"\'\n'
                  'set +e\nrun_deploy_step migrate database bash -c \'exit 7\'\n'
                  'exit_code=$?\nprintf "wrapper_exit=%s\\n" "$exit_code"\n')
        result = subprocess.run(['bash', '-s'], input=script, text=True, capture_output=True, check=True)
        self.assertRegex(result.stdout,
                         r'STEP_START step=deps command=requirements at=\d{4}-\d\d-\d\d '
                         r'\d\d:\d\d:\d\d\.\d{3}')
        self.assertRegex(result.stdout,
                         r'STEP_END step=deps command=requirements at=\d{4}-\d\d-\d\d '
                         r'\d\d:\d\d:\d\d\.\d{3} duration_ms=\d+ exit_code=0')
        self.assertRegex(result.stdout,
                         r'STEP_END step=migrate command=database .* duration_ms=\d+ exit_code=7')
        self.assertIn('wrapper_exit=7', result.stdout)

    def test_new_server_is_verified_before_switching_the_proxy_or_stopping_old_processes(self):
        source = (ROOT / 'start_server-staging.sh').read_text(encoding='utf-8')
        ready = source.index('if [ "$HEALTH_OK" -eq 1 ]; then')
        switch = source.index('mv "$HTACCESS_TEMP" "$WEB_ROOT/.htaccess"')
        stop = source.index('kill -TERM $OLD_PIDS')
        self.assertLess(ready, switch)
        self.assertLess(switch, stop)
        self.assertNotIn('pkill -9', source)
        self.assertIn('8>&- 9>&- &', source)
        self.assertIn('kill -0 "$NEW_PID"', source)
        self.assertIn('--pid "$APP_DIR/.staging-gunicorn-$SELECTED_PORT.pid"', source)
        self.assertIn('readlink "/proc/$old_pid/cwd"', source)


if __name__ == '__main__':
    unittest.main()
