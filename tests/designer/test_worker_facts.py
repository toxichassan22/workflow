"""The designer worker reads the slide's section, not the whole project.

A slide edit used to carry every project section. The scoped worker keeps the
shared identity and the section it edits; the executive summary is the one
section that still needs the full brief.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db


PROJECT = {
    'project_name': 'THE VIEW',
    'project_type': 'سكني',
    'market_study_data': json.dumps(
        {'one_block_summary': 'MARKET_MARKER'}, ensure_ascii=False),
    'team_selection': json.dumps(
        {'local': [{'name': 'TEAM_MARKER', 'role': 'مستشار'}]}, ensure_ascii=False),
}


class WorkerFactScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'worker-facts.db')
        import app as application_module
        cls.application = application_module
        with cls.application.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            db.close_db()
        except Exception:
            pass
        db.DB_PATH = cls.previous_db_path
        cls.temp_dir.cleanup()

    def _facts(self, section_key):
        ctx = {
            'project_data': PROJECT,
            'tenant_id': None,
            'creative_images': {},
        }
        slide = {
            'title': 'شريحة',
            'section_key': section_key,
            'html': '<div class="slide"></div>',
        }
        return self.application._agent_worker_facts(ctx, slide)

    def test_worker_facts_follow_the_slide_section(self):
        facts = self._facts('financial')
        self.assertIn('THE VIEW', facts)
        self.assertNotIn('MARKET_MARKER', facts)
        self.assertNotIn('TEAM_MARKER', facts)

    def test_executive_summary_keeps_the_full_brief(self):
        facts = self._facts('executive_summary')
        self.assertIn('MARKET_MARKER', facts)
        self.assertIn('TEAM_MARKER', facts)


if __name__ == '__main__':
    unittest.main()
