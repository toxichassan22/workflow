"""Market research trace persistence, worker wiring, and tenant access."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class MarketResearchTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_dir = tempfile.TemporaryDirectory()
        cls.uploads_dir = tempfile.TemporaryDirectory()
        cls.original_db = db.DB_PATH
        db.DB_PATH = os.path.join(cls.db_dir.name, 'market-trace.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.original_uploads = application_module.UPLOADS_DIR
        application_module.UPLOADS_DIR = os.path.join(cls.uploads_dir.name, 'uploads')
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant(
                'Trace test', 'trace@example.test', 'hash', 'trace-test')
        cls.token = auth.create_token(
            cls.tenant, 'trace@example.test', user_id=None,
            user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.module.UPLOADS_DIR = cls.original_uploads
        db.DB_PATH = cls.original_db
        cls.db_dir.cleanup()
        cls.uploads_dir.cleanup()

    def test_worker_writes_trace_and_download_route_is_tenant_scoped(self):
        module = self.module
        job_id = 'markettrace01'
        module._write_market_job(self.tenant, job_id, {
            'status': 'queued', 'success': True, 'kind': 'summary',
            'payload': {'kind': 'summary', 'data': {}}, 'actor': {},
        })

        def fake_execute(_data, tenant_id=None, progress=None,
                         resume_state=None, checkpoint=None, trace_writer=None):
            self.assertEqual(tenant_id, self.tenant)
            self.assertTrue(callable(trace_writer))
            trace_writer({
                'event': 'browser_step', 'researcher': 'transactions_and_rents',
                'tool': 'open_url', 'purpose': 'فتح تقرير سكني',
                'arguments': {'url': 'https://sakani.sa/reports-and-data'},
                'result': {'url': 'https://sakani.sa/reports-and-data',
                           'text': 'ظهرت بيانات السوق'},
            })
            return {'success': False, 'failureReason': 'search_not_run',
                    'error': 'تعذر إكمال البحث'}

        with self.app.app_context(), patch.object(
                module, '_execute_market_summary', side_effect=fake_execute):
            module._market_job_worker(
                self.app, self.tenant, 'summary', {}, job_id)

        job = module._read_market_job(self.tenant, job_id)
        self.assertEqual(job['status'], 'failed')
        path = module._market_research_trace_path(self.tenant, job_id)
        with open(path, encoding='utf-8') as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(records[0]['event'], 'market_study_job_started')
        self.assertEqual(records[1]['event'], 'browser_step')
        self.assertIn('ظهرت بيانات السوق', records[1]['result']['text'])

        headers = {'Authorization': 'Bearer ' + self.token}
        status = self.app.test_client().get(
            f'/api/market-study/jobs/{job_id}', headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()['researchTraceUrl'],
                         f'/api/market-study/jobs/{job_id}/trace')
        trace = self.app.test_client().get(
            f'/api/market-study/jobs/{job_id}/trace', headers=headers)
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(trace.mimetype, 'application/x-ndjson')
        self.assertIn('ظهرت بيانات السوق', trace.get_data(as_text=True))
        trace.close()

        with self.app.app_context():
            other = db.create_tenant(
                'Other trace test', 'other-trace@example.test', 'hash',
                'other-trace-test')
        other_token = auth.create_token(
            other, 'other-trace@example.test', user_id=None,
            user_role='company_admin')
        denied = self.app.test_client().get(
            f'/api/market-study/jobs/{job_id}/trace',
            headers={'Authorization': 'Bearer ' + other_token})
        self.assertEqual(denied.status_code, 404)

    def test_reaggregate_only_loads_trace_reports_without_browsing(self):
        module = self.module
        job_id = 'reaggtest01'
        trace_path = module._market_research_trace_path(self.tenant, job_id)
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with open(trace_path, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'event': 'market_study_job_started'}) + '\n')
            handle.write(json.dumps({
                'event': 'researcher_result',
                'researcher': 'development_and_supply',
                'hosts': ['nhc.sa'],
                'city': 'جدة',
                'district': '',
                'searched': True,
                'citation_urls': ['https://nhc.sa/ar/projects/al-sadan'],
                'parsed': {'findings': [{'title': 'مشروع السدن', 'details': '2.5 مليار'}]},
            }) + '\n')

        found_path = module._find_market_research_trace_file(self.tenant, job_id)
        self.assertEqual(found_path, trace_path)

        reports, citations = module._load_market_research_trace_reports(found_path)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['research_group'], 'development_and_supply')
        self.assertEqual(reports[0]['research_output']['findings'][0]['title'], 'مشروع السدن')
        self.assertIn('https://nhc.sa/ar/projects/al-sadan', citations)

        # When job_id is omitted, it finds the newest trace file for the tenant
        auto_found = module._find_market_research_trace_file(self.tenant)
        self.assertEqual(auto_found, trace_path)


if __name__ == '__main__':
    unittest.main()
