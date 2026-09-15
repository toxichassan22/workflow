"""Workflow gates from the project-file lifecycle build (t13-t18, d03, d05).

Covers what the older suites did not: section-approval expiry, the generation
input snapshot, the generation_jobs run record and its stale sweep, the
final-file content hash, the gated export download, and copy/archive hygiene.
Runs against a temporary SQLite database and never calls Google or an AI API.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class WorkflowGateDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'workflow-gates.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Tenant', 'tenant', 'tenant@example.test', 'hash', 'free'),
        )
        conn.execute(
            "INSERT INTO tenant_branding (tenant_id, company_name) VALUES ('tenant-1', 'Tenant')")
        conn.commit()
        db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'برج المشرق', 'city': 'الرياض'},
            {'basic': 'approved'}, 'draft', draft_id='draft-1',
        )
        db.record_ledger_credit('tenant-1', 100, note='شحن تجريبي')

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _estimate(self, points=0):
        estimate = db.estimate_generation_cost('tenant-1', draft_id='draft-1', slides_count=8)
        estimate['estimated_points'] = points
        estimate['estimated_cost_usd'] = points / 1000.0
        return estimate

    # ── d05: a section approval is valid for a bounded window ────────────

    def test_approved_version_carries_expiry_from_tenant_window(self):
        db.update_branding('tenant-1', section_approval_days=7)
        self.assertEqual(db.get_section_approval_validity_days('tenant-1'), 7)
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        decided = db.decide_section_version(
            'tenant-1', version['id'], 'approved', 'user-2', 'Approver')
        self.assertEqual(decided['status'], 'approved')
        self.assertTrue(decided['expires_at'])
        stored = db.get_section_version('tenant-1', version['id'], include_snapshot=False)
        self.assertFalse(stored['is_expired'])

    def test_expired_section_approval_blocks_generation_request(self):
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        db.decide_section_version('tenant-1', version['id'], 'approved', 'user-2', 'Approver')
        conn = db.get_db()
        conn.execute(
            "UPDATE section_versions SET expires_at = '2000-01-01T00:00:00' WHERE id = ?",
            (version['id'],))
        conn.commit()
        self.assertIn('basic', db.expired_approved_sections('tenant-1', 'draft-1'))
        refused = db.create_generation_approval(
            'tenant-1', 'draft-1', self._estimate(), 'user-1', 'User One')
        self.assertEqual(refused.get('error'), 'section_version_expired')
        self.assertIn('basic', refused.get('sections'))

    # ── t14-04/t15-01: the priced inputs are frozen and verified ─────────

    def test_generation_decision_refuses_inputs_that_drifted(self):
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        snapshot = {'draft_hash': db.draft_generation_input_hash(draft.get('draft_data') or {})}
        approval = db.create_generation_approval(
            'tenant-1', 'draft-1', self._estimate(), 'user-1', 'User One',
            input_snapshot=snapshot)
        self.assertEqual(approval['status'], 'pending')
        stored = db.get_generation_approval('tenant-1', approval['id'])
        self.assertEqual(
            db._json_object(stored['input_snapshot']).get('draft_hash'), snapshot['draft_hash'])
        # The draft is now locked to normal saves; the drift below is the kind
        # a stale editor session or a racing write could still leave behind.
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'برج آخر'
        conn = db.get_db()
        conn.execute(
            'UPDATE project_drafts SET draft_data = ? WHERE id = ?',
            (json.dumps(changed, ensure_ascii=False), 'draft-1'))
        conn.commit()
        refused = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'Approver')
        self.assertEqual(refused.get('error'), 'inputs_changed')
        self.assertEqual(
            db.get_generation_approval('tenant-1', approval['id'])['status'], 'pending')
        # Restoring the reviewed inputs lets the same request be approved.
        conn.execute(
            'UPDATE project_drafts SET draft_data = ? WHERE id = ?',
            (json.dumps(draft['draft_data'], ensure_ascii=False), 'draft-1'))
        conn.commit()
        allowed = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'Approver')
        self.assertEqual(allowed.get('status'), 'approved')

    # ── t14-05: the run is a job record; the sweep frees dead runs ───────

    def test_generation_job_lifecycle_idempotency_and_stale_sweep(self):
        estimate = self._estimate(points=25000)
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        snapshot = {'draft_hash': db.draft_generation_input_hash(draft.get('draft_data') or {})}
        approval = db.create_generation_approval(
            'tenant-1', 'draft-1', estimate, 'user-1', 'User One',
            input_snapshot=snapshot)
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'Approver')
        self.assertEqual(decided.get('status'), 'approved', decided)
        self.assertTrue(decided.get('reservation_id'))
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 75.0)

        job = db.create_generation_job(
            'tenant-1', approval_id=approval['id'], draft_id='draft-1',
            slides_total=8, created_by='user-1', idempotency_key='run-1')
        self.assertEqual(job['status'], 'queued')
        same = db.create_generation_job(
            'tenant-1', approval_id=approval['id'], draft_id='draft-1',
            idempotency_key='run-1')
        self.assertEqual(same['id'], job['id'])

        running = db.update_generation_job(job['id'], status='running', progress=40, slides_done=3)
        self.assertTrue(running['started_at'])
        self.assertEqual(running['progress'], 40)
        self.assertEqual(running['slides_done'], 3)

        # The worker died: heartbeat goes silent, the sweep fails the run and
        # releases the escrow so the wallet and the draft are never stranded.
        conn = db.get_db()
        conn.execute(
            "UPDATE generation_jobs SET heartbeat_at = '2000-01-01T00:00:00' WHERE id = ?",
            (job['id'],))
        conn.commit()
        self.assertEqual(db.sweep_stale_generation_jobs('tenant-1', timeout_minutes=30), 1)
        swept = db.get_generation_job(job['id'])
        self.assertEqual(swept['status'], 'failed')
        self.assertEqual(swept['error'], 'job_timeout')
        self.assertTrue(swept['finished_at'])
        reservations = db.list_point_reservations('tenant-1', status='released')
        self.assertEqual(len(reservations), 1)
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 100.0)
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        self.assertNotEqual(draft['status'], 'generating')

    def test_completed_job_marks_finished_and_settles_once(self):
        estimate = self._estimate(points=25000)
        approval = db.create_generation_approval(
            'tenant-1', 'draft-1', estimate, 'user-1', 'User One')
        db.decide_generation_approval('tenant-1', approval['id'], 'approved', 'user-2', 'Approver')
        job = db.create_generation_job(
            'tenant-1', approval_id=approval['id'], draft_id='draft-1', slides_total=8)
        done = db.update_generation_job(
            job['id'], status='completed', progress=100, slides_done=8, actual_cost_usd=12.5)
        self.assertTrue(done['finished_at'])
        self.assertEqual(done['actual_cost_usd'], 12.5)
        settled = db.settle_generation_approval(
            'tenant-1', approval['id'], job['id'], consumed=True, settled_by='user-1')
        self.assertEqual(settled['status'], 'consumed')
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        self.assertEqual(draft['status'], 'generated_draft')

    # ── t15: the final gate pins the reviewed content and stamps bytes ────

    def test_final_request_hash_blocks_approve_after_edit_and_rerequest(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status, project_data, slides_data) "
            "VALUES ('pres-1', 'tenant-1', 'عرض', 'generated_draft', '{}', '[]')")
        conn.commit()
        request = db.request_final_file_approval('tenant-1', 'pres-1', 'user-1', 'User One', revision=1)
        self.assertEqual(request['status'], 'pending')
        self.assertTrue(request['request_hash'])

        conn.execute("UPDATE presentations SET slides_data = '[{\"html\":\"x\"}]' WHERE id = 'pres-1'")
        conn.commit()
        refused = db.decide_final_file_approval(
            'tenant-1', request['id'], 'approved', 'user-2', 'Approver')
        self.assertEqual(refused.get('error'), 'content_changed')
        self.assertEqual(
            db.latest_final_file_approval('tenant-1', 'pres-1', status='pending')['id'], request['id'])

        rejected = db.decide_final_file_approval(
            'tenant-1', request['id'], 'rejected', 'user-2', 'Approver', note='راجع الغلاف')
        self.assertEqual(rejected['status'], 'rejected')
        # Re-sending the exact content that was rejected is refused; the next
        # request has to carry an actual revision.
        conn.execute("UPDATE presentations SET slides_data = '[]' WHERE id = 'pres-1'")
        conn.commit()
        again = db.request_final_file_approval('tenant-1', 'pres-1', 'user-1', 'User One', revision=1)
        self.assertEqual(again.get('error'), 'unchanged_since_rejection')
        # A genuinely changed file opens a fresh request.
        conn.execute("UPDATE presentations SET slides_data = '[{\"html\":\"y\"}]' WHERE id = 'pres-1'")
        conn.commit()
        revised = db.request_final_file_approval('tenant-1', 'pres-1', 'user-1', 'User One', revision=2)
        self.assertEqual(revised.get('status'), 'pending')

    def test_stamp_binds_export_bytes_to_the_approval(self):
        payload = b'%PDF-stamped-bytes'
        export_path = os.path.join(self.temp_dir.name, 'outputs', 'tenant-1', 'final.pdf')
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        with open(export_path, 'wb') as handle:
            handle.write(payload)
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status, project_data, slides_data) "
            "VALUES ('pres-s', 'tenant-1', 'عرض', 'generated_draft', '{}', '[]')")
        conn.commit()
        export_id = db.create_export('pres-s', 'tenant-1', 'pdf', export_path)
        request = db.request_final_file_approval('tenant-1', 'pres-s', 'user-1', 'User One', revision=2)
        decided = db.decide_final_file_approval(
            'tenant-1', request['id'], 'approved', 'user-2', 'Approver',
            app_root=self.temp_dir.name)
        stamp = decided.get('stamped_file')
        self.assertTrue(stamp, decided)
        self.assertEqual(stamp['content_hash'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(stamp['export_id'], export_id)
        approval = db.latest_final_file_approval('tenant-1', 'pres-s', status='approved')
        self.assertEqual(approval['stamped_export_id'], export_id)

    # ── t17/t18: copies carry no approvals; archives keep the record ──────

    def test_copy_strips_approval_state_and_remaps_file_rows(self):
        conn = db.get_db()
        conn.execute(
            '''INSERT INTO project_files
               (id, tenant_id, draft_id, file_type, original_name, storage_path, mime_type,
                file_size, sha256)
               VALUES ('file-1', 'tenant-1', 'draft-1', 'document', 'دراسة.pdf',
                       'uploads/t1/file-1.pdf', 'application/pdf', 10, 'abc')''')
        conn.execute(
            'UPDATE project_drafts SET draft_data = ? WHERE id = ?',
            (json.dumps({
                'project_name': 'برج المشرق',
                'draftId': 'draft-1',
                'sectionStatuses': {'basic': 'approved'},
                'tenantSlidesData': [{'html': 'x'}],
                'location_analysis_approved': True,
                'study_file': 'file-1',
                'visual_concept': {'slots': {'cover': {'approved': True, 'imageUrl': 'u'}}},
            }, ensure_ascii=False), 'draft-1'))
        conn.execute(
            "UPDATE project_drafts SET section_statuses = '{\"basic\": \"approved\"}' WHERE id = 'draft-1'")
        conn.commit()

        result = db.copy_project_draft('tenant-1', 'draft-1', 'نسخة البرج', 'user-1', 'User One')
        self.assertNotIn('error', result)
        copied = db.get_project_draft_by_id('tenant-1', result['draft_id'])
        self.assertEqual(copied['status'], 'draft')
        self.assertEqual(copied['section_statuses'], {})
        data = copied['draft_data']
        self.assertEqual(data['project_name'], 'برج المشرق')
        for key in ('sectionStatuses', 'tenantSlidesData', 'location_analysis_approved'):
            self.assertNotIn(key, data)
        self.assertEqual(data['draftId'], result['draft_id'])
        self.assertNotEqual(data['study_file'], 'file-1')
        self.assertNotIn('approved', data['visual_concept']['slots']['cover'])
        new_file = conn.execute(
            'SELECT * FROM project_files WHERE draft_id = ?', (result['draft_id'],)).fetchone()
        self.assertTrue(new_file)
        self.assertEqual(data['study_file'], new_file['id'])
        self.assertEqual(new_file['storage_path'], 'uploads/t1/file-1.pdf')

    def test_archive_restore_and_retention_window(self):
        conn = db.get_db()
        archived = db.transition_project_draft_status(
            'tenant-1', 'draft-1', 'archived', actor_id='user-1', actor_name='User One',
            reason='أرشفة العرض')
        self.assertNotIn('error', archived)
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        self.assertEqual(draft['status'], 'archived')
        self.assertTrue(draft['archived_at'])
        # A still-recent archive survives the retention sweep.
        self.assertEqual(db.purge_expired_archives('tenant-1')['drafts'], 0)
        restored = db.transition_project_draft_status(
            'tenant-1', 'draft-1', 'draft', actor_id='user-1', actor_name='User One',
            reason='استعادة من الأرشيف')
        self.assertNotIn('error', restored)
        draft = db.get_project_draft_by_id('tenant-1', 'draft-1')
        self.assertEqual(draft['status'], 'draft')
        self.assertIsNone(draft['archived_at'])
        # Only records past the retention window are purged.
        db.transition_project_draft_status('tenant-1', 'draft-1', 'archived', reason='أرشفة')
        conn.execute(
            "UPDATE project_drafts SET archived_at = '2000-01-01T00:00:00' WHERE id = 'draft-1'")
        conn.commit()
        self.assertEqual(db.purge_expired_archives('tenant-1')['drafts'], 1)
        self.assertIsNone(db.get_project_draft_by_id('tenant-1', 'draft-1'))


class ExportDownloadGateTests(unittest.TestCase):
    """GET /api/exports/<id>/download: drafts ship marked, officials gated."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'export-gate.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.OUTPUT_DIR = os.path.join(cls.temp_dir.name, 'outputs')

        with cls.app.app_context():
            cls.tenant = db.create_tenant('Gate Co', 'gate@example.test', 'hash-g', 'gate-co')
        cls.token = auth.create_token(
            cls.tenant, 'gate@example.test', user_id=None,
            user_name='Gate Co', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _fixture(self):
        with self.app.app_context():
            conn = db.get_db()
            conn.execute('DELETE FROM exports')
            conn.execute('DELETE FROM final_file_approvals')
            conn.execute('DELETE FROM presentations')
            conn.execute(
                "INSERT INTO presentations (id, tenant_id, title, status, project_data, slides_data) "
                "VALUES ('pres-g', ?, 'عرض', 'generated_draft', '{}', '[]')",
                (self.tenant,))
            conn.commit()
            out_dir = os.path.join(self.application_module.OUTPUT_DIR, self.tenant)
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, 'deck.pdf')
            with open(path, 'wb') as handle:
                handle.write(b'%PDF-gate')
            export_id = db.create_export('pres-g', self.tenant, 'pdf', path)
        return export_id

    def test_unapproved_export_is_gated_and_draft_mode_is_marked(self):
        client = self.app.test_client()
        export_id = self._fixture()

        blocked = client.get(f'/api/exports/{export_id}/download', headers=self.headers())
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.get_json().get('error_code'), 'final_approval_required')

        draft = client.get(f'/api/exports/{export_id}/download?draft=1', headers=self.headers())
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.headers.get('X-Draft-Mode'), '1')
        self.assertIn('DRAFT-', draft.headers.get('Content-Disposition', ''))

    def test_approved_export_downloads_officially(self):
        client = self.app.test_client()
        export_id = self._fixture()
        with self.app.app_context():
            request = db.request_final_file_approval(
                self.tenant, 'pres-g', 'user-1', 'User One', revision=1)
            decided = db.decide_final_file_approval(
                self.tenant, request['id'], 'approved', 'user-2', 'Approver',
                app_root=self.application_module.OUTPUT_DIR)
            self.assertEqual(decided.get('status'), 'approved', decided)
        response = client.get(f'/api/exports/{export_id}/download', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get('X-Draft-Mode'))
        self.assertNotIn('DRAFT-', response.headers.get('Content-Disposition', ''))

    def test_downloads_library_only_serves_approved_rows(self):
        export_id = self._fixture()
        with self.app.app_context():
            row = db.record_download(
                self.tenant, 'deck.pdf', presentation_id='pres-g', export_id=export_id)
            self.assertEqual(row['approval_status'], 'pending')
            listed = db.list_downloads(self.tenant)
            self.assertIsNone(listed[0]['download_url'])
            request = db.request_final_file_approval(
                self.tenant, 'pres-g', 'user-1', 'User One', revision=1)
            db.decide_final_file_approval(
                self.tenant, request['id'], 'approved', 'user-2', 'Approver',
                app_root=self.application_module.OUTPUT_DIR)
            row = db.record_download(
                self.tenant, 'deck.pdf', presentation_id='pres-g', export_id=export_id)
            self.assertEqual(row['approval_status'], 'approved')
            listed = [item for item in db.list_downloads(self.tenant) if item['id'] == row['id']]
            self.assertEqual(listed[0]['download_url'], f'/api/exports/{export_id}/download')


if __name__ == '__main__':
    unittest.main()
