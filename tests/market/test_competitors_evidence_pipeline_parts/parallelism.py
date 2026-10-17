from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline


class _RecordingExecutor:
    def __init__(self, max_workers, calls):
        calls.append(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def map(self, function, items):
        return [function(item) for item in items]


class ParallelismTests(pipeline._MarketTestBase):
    def test_pending_competitor_checks_use_up_to_100_workers(self):
        module = self.module
        rows = [{'name': f'منافس {index}'} for index in range(125)]
        observed = []

        class RecordingExecutor(_RecordingExecutor):
            def __init__(self, max_workers):
                super().__init__(max_workers, observed)

        with self.app.app_context(), \
                patch('concurrent.futures.ThreadPoolExecutor', RecordingExecutor), \
                patch.object(module, '_verify_competitor_row_pooled'), \
                patch.object(module, '_close_verify_thread_browser'):
            module._verify_competitor_rows(
                rows, {}, {}, evidence_pool=None, deadline=None)

        self.assertEqual(observed, [100])
