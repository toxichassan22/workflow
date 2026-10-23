"""AI usage metering carries the context and thinking figures.

Prompt tokens alone hid two costs: the provider's cached prefix and the
reasoning tokens behind a scoped edit. These cases pin the extraction and the
database round-trip, so the before/after report can see both.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db


class AiUsageMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'ai-usage-metrics.db')
        import app as application_module
        cls.application = application_module
        with cls.application.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant(
                'Metrics Co', 'metrics@example.test', 'hash', 'metrics-co')

    @classmethod
    def tearDownClass(cls):
        try:
            db.close_db()
        except Exception:
            pass
        db.DB_PATH = cls.previous_db_path
        cls.temp_dir.cleanup()

    def test_provider_usage_reads_cached_and_reasoning_tokens(self):
        _, usage = self.application._extract_openrouter_usage({
            'id': 'gen-metrics',
            'usage': {
                'prompt_tokens': 120,
                'completion_tokens': 30,
                'total_tokens': 150,
                'cost': '0.0123',
                'prompt_tokens_details': {'cached_tokens': 80},
                'completion_tokens_details': {'reasoning_tokens': 20},
            },
        })
        self.assertEqual(usage['prompt_tokens'], 120)
        self.assertEqual(usage['cached_tokens'], 80)
        self.assertEqual(usage['reasoning_tokens'], 20)
        self.assertAlmostEqual(usage['cost_usd'], 0.0123)

    def test_usage_record_persists_context_and_thinking_metrics(self):
        with self.application.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant, 'test-model', flow='slide',
                prompt_tokens=120, completion_tokens=30, total_tokens=150,
                cached_tokens=80, reasoning_tokens=20, duration_ms=1234,
                context_hash='abc123', context_chars=4096,
                cost_usd=0.01, cost_source='response', attempt_status='settled')
            row = db.get_db().execute(
                'SELECT * FROM ai_usage_events WHERE id = ?', (event_id,)).fetchone()
        self.assertEqual(row['cached_tokens'], 80)
        self.assertEqual(row['reasoning_tokens'], 20)
        self.assertEqual(row['duration_ms'], 1234)
        self.assertEqual(row['context_hash'], 'abc123')
        self.assertEqual(row['context_chars'], 4096)

    def test_attempt_update_persists_thinking_and_duration(self):
        with self.application.app.app_context():
            event_id = db.begin_ai_usage_attempt(
                self.tenant, 'test-model', flow='designer_chat',
                context_hash='def456', context_chars=1024)
            db.update_ai_usage_attempt(
                event_id, prompt_tokens=200, completion_tokens=50, total_tokens=250,
                cached_tokens=100, reasoning_tokens=25, duration_ms=777)
            row = db.get_db().execute(
                'SELECT * FROM ai_usage_events WHERE id = ?', (event_id,)).fetchone()
        self.assertEqual(row['cached_tokens'], 100)
        self.assertEqual(row['reasoning_tokens'], 25)
        self.assertEqual(row['duration_ms'], 777)
        self.assertEqual(row['context_hash'], 'def456')
        self.assertEqual(row['context_chars'], 1024)


if __name__ == '__main__':
    unittest.main()
