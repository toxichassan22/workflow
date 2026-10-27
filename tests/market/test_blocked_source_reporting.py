"""A blocked source is reported, never counted as an empty market."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import db
import evidence
import market_study


class BlockedSourceReportingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'blocked-sources.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_blocked_and_failed_sources_are_named_in_the_note(self):
        pool = evidence.EvidencePool()
        pool.mark_failed('https://sa.aqar.fm/listings', 'blocked')
        pool.mark_failed('https://www.sakani.sa/reports', 'http_403')
        pool.mark_failed('https://rei.rega.gov.sa/ar', 'timeout')
        note = self.module._blocked_sources_note(pool)
        self.assertIn('2', note)
        self.assertIsInstance(note, str)
        self.assertIn('محجوب', note)
        self.assertIn('sa.aqar.fm', note)
        self.assertIn('sakani.sa', note)
        self.assertNotIn('rei.rega.gov.sa', note)

    def test_a_clean_run_has_no_blocked_note(self):
        pool = evidence.EvidencePool()
        pool.add_page('https://example.com/page', title='page', content='محتوى')
        self.assertEqual(self.module._blocked_sources_note(pool), '')


if __name__ == '__main__':
    unittest.main()
