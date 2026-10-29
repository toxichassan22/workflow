"""Every paid generation call the client makes must be reachable by the stop.

The stop button kept silently losing flows: a new paid request was added with
a plain ``api('POST', ...)``, the card closed, and the provider kept being
called. The rule this suite enforces is the one the owner asked for — a paid
call either carries its own run handle (``apiStoppable``) or is a job start
whose returned job id is registered for the stop.

A new paid call that is neither fails this suite, so the flow has to declare
itself instead of quietly escaping the stop.

Run from the repo root:
    python -m unittest tests.platform.test_generation_stop_coverage
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

PAID_PREFIXES = (
    '/api/generate-images',
    '/api/generate-slide-single',
    '/api/slide-plan',
    '/api/visual-concept/',
    '/api/extract-croquis',
    '/api/site-analysis',
    '/api/analyze-site',
    '/api/preview-map-data',
    '/api/generate-map-image',
    '/api/market-study/',
    '/api/market-competitors/',
    '/api/best-use/',
    '/api/executive-content/',
)

CALL_RE = re.compile(r"(apiStoppable|apiWithTimeout|api)\(\s*'POST'\s*,\s*'([^']+)'")

# Job starts and polls: the call answers a job id (or reads one), and the flow
# registers that id as a run, so the stop reaches the worker it started.
RUN_HANDLE_BY_JOB = {
    '/api/best-use/': 'bestUseAwaitJob registers the returned job id',
    '/api/extract-croquis': 'the croquis flow registers the queued job id',
    '/api/market-study/competitors': 'market jobs register their job id',
    '/api/market-study/summary': 'market jobs register their job id',
    '/api/market-study/summary/chat': 'pollMarketStudyJob registers the run',
    '/api/market-study/summary/consolidate': 'pollMarketStudyJob registers the run',
    '/api/market-study/jobs/': 'the poll of an already registered run',
    '/api/slide-plan': 'the plan job id is registered while it polls',
    '/api/generate-slide-single-job': 'the slide job id is registered by the deck loop',
    '/api/analyze-site': 'the site-analysis job id is registered while it polls',
}

# Calls that never reach a paid provider, so there is no work to stop.
PROVIDER_FREE = {
    '/api/generate-map-image': 'the overlay-only recompose draws the stored frame locally',
    '/api/visual-concept/preflight': 'the preflight validates the payload, no provider call',
}


def _paid_client_calls():
    calls = set()
    for path in sorted((ROOT / 'assets' / 'js').rglob('*.js')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for match in CALL_RE.finditer(text):
            helper, route = match.group(1), match.group(2)
            if not route.startswith(PAID_PREFIXES):
                continue
            calls.add((helper, route, path.as_posix()))
    return calls


def _covered_by(route, table):
    return any(route == key or route.startswith(key) for key in table)


class GenerationStopCoverageTests(unittest.TestCase):
    def test_every_paid_client_call_is_stoppable_or_a_job_start(self):
        uncovered = []
        for helper, route, owner in sorted(_paid_client_calls()):
            if helper == 'apiStoppable':
                continue
            if _covered_by(route, RUN_HANDLE_BY_JOB) or _covered_by(route, PROVIDER_FREE):
                continue
            uncovered.append(f'{helper} POST {route} ({owner})')
        self.assertFalse(
            uncovered,
            'These paid calls carry no run handle: use apiStoppable, or classify '
            'them as a job start / provider-free call with the reason.\n'
            + '\n'.join(uncovered))

    def test_the_stoppable_helper_registers_and_releases_the_handle(self):
        source = (ROOT / 'assets' / 'js' / '13-visual' / '04_generation_stop.js').read_text(
            encoding='utf-8')
        self.assertIn('async function apiStoppable(', source)
        self.assertIn('registerTenantGenerationRun(runId);', source)
        self.assertIn('releaseTenantGenerationRun(runId);', source)
        self.assertIn("'X-Run-Id': runId", source)

    def test_a_stopped_inline_request_can_be_aborted_in_the_browser(self):
        """The page must stop waiting, not only the server stop working."""
        source = (ROOT / 'assets' / 'js' / '13-visual' / '04_generation_stop.js').read_text(
            encoding='utf-8')
        self.assertIn('abortTenantGenerationRun(runId);', source)
        self.assertIn('new AbortController()', source)

    def test_the_server_binds_the_run_a_client_sends(self):
        source = (ROOT / 'app_parts' / '26a_run_control.py').read_text(encoding='utf-8')
        self.assertIn('def _bind_request_run()', source)
        self.assertIn('run_control.REQUEST_RUN_HEADER', source)
        self.assertIn('def _unbind_request_run(', source)


if __name__ == '__main__':
    unittest.main()
