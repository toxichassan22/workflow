"""Task progress is measured, never guessed.

The progress card used to climb on a client-side timer, so a job that was stuck
still looked like it was moving. These tests pin the contract that replaced it:
the server names the step it is on, a running job never reports 100, and the
slide-plan worker publishes those steps in the order it walks them.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import task_progress


class StepPlanTests(unittest.TestCase):
    def test_plan_names_the_real_stages_in_order(self):
        steps = task_progress.steps('slide_plan')
        self.assertEqual(
            [step['key'] for step in steps],
            ['inputs', 'ai', 'arrange', 'ready'])
        self.assertEqual(
            [step['label'] for step in steps],
            ['تجهيز بيانات المشروع', 'تحليل البيانات وبناء الهيكل',
             'ترتيب الأقسام والشرائح', 'تجهيز خطة العرض'])
        self.assertEqual(task_progress.payload('slide_plan', 'ai')['stepTotal'], 4)

    def test_progress_counts_only_steps_already_entered(self):
        expected = {
            'inputs': (0, 'تجهيز بيانات المشروع'),
            'ai': (25, 'تحليل البيانات وبناء الهيكل'),
            'arrange': (50, 'ترتيب الأقسام والشرائح'),
            'ready': (75, 'تجهيز خطة العرض'),
        }
        for step_key, (value, label) in expected.items():
            with self.subTest(step=step_key):
                payload = task_progress.payload('slide_plan', step_key)
                self.assertEqual(payload['progress'], value)
                self.assertEqual(payload['step'], step_key)
                self.assertEqual(payload['stepLabel'], label)

    def test_a_running_job_never_reports_one_hundred(self):
        values = [
            task_progress.payload('slide_plan', key)['progress']
            for key in ('inputs', 'ai', 'arrange', 'ready')
        ]
        self.assertEqual(sorted(values), values)
        self.assertLess(max(values), 100)

    def test_completion_is_the_only_hundred(self):
        done = task_progress.payload('slide_plan', 'ready', complete=True)
        self.assertEqual(done['progress'], 100)
        self.assertEqual(done['step'], 'ready')

    def test_a_known_unit_count_credits_its_finished_share(self):
        quarter = task_progress.payload('slide_plan', 'arrange', done=1, total=4)
        half = task_progress.payload('slide_plan', 'arrange', done=2, total=4)
        self.assertGreater(quarter['progress'], 50)
        self.assertGreater(half['progress'], quarter['progress'])
        self.assertLess(half['progress'], 75)

    def test_a_unit_count_without_a_total_credits_nothing(self):
        self.assertEqual(
            task_progress.payload('slide_plan', 'arrange', done=3)['progress'], 50)
        self.assertEqual(
            task_progress.payload('slide_plan', 'arrange', done=3, total=0)['progress'], 50)

    def test_an_unknown_plan_or_step_is_refused(self):
        with self.assertRaises(ValueError):
            task_progress.steps('no_such_plan')
        with self.assertRaises(ValueError):
            task_progress.payload('slide_plan', 'no_such_step')


class SlidePlanJobProgressTests(unittest.TestCase):
    """The planner publishes each real boundary, not just its first sentence."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        import db
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'task-progress.db')
        import app as application
        cls.application = application

    @classmethod
    def tearDownClass(cls):
        import db
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def test_worker_writes_the_plan_steps_in_the_order_it_walks_them(self):
        writes = []

        def fake_write(namespace, tenant_id, job_id, body):
            writes.append(dict(body))

        def fake_execute(project_data, tenant_id, branding, images=None,
                         target_section_keys=None, progress=None):
            # The worker must hand the planner a reporter that lands in the job
            # file; these four calls are the real boundaries inside it.
            for step_key in ('inputs', 'ai', 'arrange', 'ready'):
                progress(step_key, detail='مرحلة ' + step_key)
            return {'success': True, 'plan': {'slides': [{'title': 'غلاف'}]}}

        with patch.object(self.application, '_write_job', side_effect=fake_write), \
                patch.object(self.application, '_emergency_slide_plan', return_value={}), \
                patch.object(self.application, '_execute_slide_plan', side_effect=fake_execute):
            self.application._slide_plan_job_worker(
                self.application.app, 'tenant-progress', {'project_name': 'برج'},
                {}, {}, 'job-progress-1')

        step_writes = [write for write in writes
                       if write.get('step') and write['status'] == 'running']
        self.assertEqual(
            [write['step'] for write in step_writes],
            ['inputs', 'ai', 'arrange', 'ready'])
        for write in step_writes:
            self.assertEqual(write['stepTotal'], 4)
            self.assertEqual(len(write['steps']), 4)
            self.assertTrue(write['progressMeasured'])
        values = [write['progress'] for write in step_writes]
        self.assertEqual(values, sorted(values))
        self.assertLess(max(values), 100)

        # Completion is the only write that may say 100, and it names the step
        # it finished rather than dropping the checklist.
        final = writes[-1]
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(final['progress'], 100)
        self.assertEqual(final['step'], 'ready')
        self.assertTrue(final['progressMeasured'])
        self.assertEqual([step['key'] for step in final['steps']],
                         ['inputs', 'ai', 'arrange', 'ready'])

    def test_a_failed_request_never_reports_finished(self):
        writes = []

        def fake_write(namespace, tenant_id, job_id, body):
            writes.append(dict(body))

        def fake_execute(project_data, tenant_id, branding, images=None,
                         target_section_keys=None, progress=None):
            progress('inputs')
            return {'success': False, 'error': 'تعذر إعداد الخطة', 'http_status': 503}

        with patch.object(self.application, '_write_job', side_effect=fake_write), \
                patch.object(self.application, '_emergency_slide_plan', return_value={}), \
                patch.object(self.application, '_execute_slide_plan', side_effect=fake_execute):
            self.application._slide_plan_job_worker(
                self.application.app, 'tenant-progress', {}, {}, {}, 'job-progress-2')

        final = writes[-1]
        self.assertEqual(final['status'], 'failed')
        self.assertNotEqual(final.get('progress'), 100)


if __name__ == '__main__':
    unittest.main()
