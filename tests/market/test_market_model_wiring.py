"""The market research must ride the configured market model.

``MARKET_STUDY_MODEL`` is the owner's knob for the market brain — the model
that searches for the competitors, opens their pages and reads the price off
them. A market browse-agent call that passes a model of its own answers on a
different brain than the one that was configured, and the price verification
stops being the same mind that found the page.

The seam itself (``_browse_agent_call``) already falls back to
``MARKET_STUDY_MODEL``. This suite guards the call sites, because the failure
mode is silent: the market still returns rows, just from another model.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MARKET_PARTS = ROOT / 'app_parts' / '17_market'


class MarketModelWiringTests(unittest.TestCase):

    def _market_source(self):
        return '\n'.join(
            path.read_text(encoding='utf-8')
            for path in sorted(MARKET_PARTS.glob('*.py')))

    def test_no_market_browse_call_passes_a_model_of_its_own(self):
        source = self._market_source()
        calls = re.findall(r'(?<!def )_browse_agent_call\((.*?)\)\s*\n', source, re.S)
        self.assertTrue(calls, 'the market browse-agent seam disappeared')
        for args in calls:
            self.assertNotIn(
                'model=', args,
                'a market browse call must follow MARKET_STUDY_MODEL, not a model of its own')

    def test_the_market_seam_falls_back_to_the_configured_model(self):
        import agent
        import app as application_module
        seen = {}

        def fake_run(task, **kwargs):
            seen.update(kwargs)
            return {'choices': [{'message': {'content': '{}'}}]}

        with patch.object(agent, 'run_browse_agent', side_effect=fake_run):
            application_module._browse_agent_call(
                'SYS-BRIEF', 'USER-ASK', {'tenant_id': 't-1', 'flow': 'market'})
        self.assertEqual(seen.get('model'), application_module.MARKET_STUDY_MODEL)


if __name__ == '__main__':
    unittest.main()
