"""Recovery must not relaunch market jobs owned by a live worker."""

import json
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
_MODULES = ROOT / 'modules'
if _MODULES.is_dir():
    for _dirpath, _dirnames, _filenames in os.walk(_MODULES):
        if any(_filename.endswith('.py') for _filename in _filenames):
            if _dirpath not in sys.path:
                sys.path.insert(0, _dirpath)

import app as application_module


class MarketJobRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.uploads_patch = patch.object(
            application_module, 'UPLOADS_DIR', self.temp_dir.name)
        self.uploads_patch.start()
        self.addCleanup(self.uploads_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def _write_job(self, job_id, owner_pid):
        path = application_module._job_path('.market_jobs', 'tenant-recovery', job_id)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({
                'status': 'running',
                'success': True,
                'kind': 'summary',
                'updatedAt': time.time(),
                'pid': owner_pid,
                'payload': {'kind': 'summary', 'data': {'draftId': 'draft-1'}},
                'actor': {},
            }, handle)
        return path

    def test_live_foreign_owner_is_not_dispatched_again(self):
        path = self._write_job('marketlive01', os.getpid() + 1)
        with patch.object(application_module, '_job_owner_pid_is_alive',
                          return_value=True), \
                patch.object(application_module, '_redispatch_job') as dispatch:
            resumed = application_module._resume_interrupted_jobs()

        self.assertEqual(resumed, 0)
        dispatch.assert_not_called()
        with open(path, encoding='utf-8') as handle:
            self.assertNotIn('resumed', json.load(handle))

    def test_dead_owner_is_dispatched_once_and_claimed_by_current_process(self):
        path = self._write_job('marketdead01', os.getpid() + 100000)

        def pid_is_alive(owner_pid):
            return int(owner_pid) == os.getpid()

        with patch.object(application_module, '_job_owner_pid_is_alive',
                          side_effect=pid_is_alive), \
                patch.object(application_module, '_redispatch_job', return_value=True) as dispatch:
            first_resume = application_module._resume_interrupted_jobs()
            second_resume = application_module._resume_interrupted_jobs()

        self.assertEqual(first_resume, 1)
        self.assertEqual(second_resume, 0)
        dispatch.assert_called_once()
        with open(path, encoding='utf-8') as handle:
            stored = json.load(handle)
        self.assertTrue(stored.get('resumed'))
        self.assertEqual(stored.get('pid'), os.getpid())


if __name__ == '__main__':
    unittest.main()
