"""City-regulation discovery rides the self-hosted browse agent.

``modules/platform/city_regulations.py`` used to take a ``chat_fn`` and lean
on a paid server-side search plugin; that layer is gone. Discovery now runs
one ``run_browse_agent`` task whose model opens pages on headless Chromium —
the JSON it answers carries the candidate PDF urls, and an agent failure is a
warning string, never a silent memory answer. These tests fake the agent; no
network or browser is touched.

Run like every other suite::

    python -m unittest tests.platform.test_city_regulations
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT),
           str(ROOT / 'modules' / 'platform'),
           str(ROOT / 'modules' / 'web_browse')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent  # noqa: E402  modules/web_browse/agent.py
import city_regulations  # noqa: E402  modules/platform/city_regulations.py


def _agent_reply(payload):
    return {'choices': [{'message': {'role': 'assistant',
                                     'content': payload,
                                     'annotations': []}}],
            'usage': {}, 'browse_trace': []}


class CityRegulationDiscoveryTests(unittest.TestCase):

    def test_discovery_takes_no_chat_fn(self):
        """The paid-search callback seam is gone from the public surface."""
        for fn in (city_regulations.discover_city_regulation_urls,
                   city_regulations.ensure_city_regulation_paths):
            self.assertNotIn('chat_fn', inspect.signature(fn).parameters)

    def test_discovery_runs_the_browse_agent_and_parses_pdf_urls(self):
        seen = {}

        def fake_agent(task, **kwargs):
            seen['task'] = task
            seen['kwargs'] = kwargs
            return _agent_reply(
                '{"pdf_urls": ["https://amanah.gov.sa/regs.pdf",'
                ' "https://other.gov.sa/x.pdf",'
                ' "https://amanah.gov.sa/regs.pdf"]}')

        with mock.patch.object(agent, 'run_browse_agent',
                               side_effect=fake_agent):
            urls, warnings = city_regulations.discover_city_regulation_urls(
                'jeddah', 'جدة', usage_ctx={'flow': 'land'},
                hosts=['amanah-jeddah.gov.sa'])
        self.assertEqual(warnings, [])
        self.assertEqual(urls, ['https://amanah.gov.sa/regs.pdf',
                                'https://other.gov.sa/x.pdf'])
        self.assertIn('amanah-jeddah.gov.sa', seen['task'])
        self.assertEqual(seen['kwargs']['usage_ctx'], {'flow': 'land'})

    def test_discovery_empty_answer_returns_no_urls(self):
        with mock.patch.object(agent, 'run_browse_agent',
                               return_value=_agent_reply('{"pdf_urls": []}')):
            urls, warnings = city_regulations.discover_city_regulation_urls(
                'hail', 'حائل')
        self.assertEqual(urls, [])
        self.assertEqual(warnings, [])

    def test_agent_error_surfaces_as_a_warning_not_urls(self):
        with mock.patch.object(
                agent, 'run_browse_agent',
                return_value={'error': {'message': 'browser dead'},
                              'browse_trace': []}):
            urls, warnings = city_regulations.discover_city_regulation_urls(
                'hail', 'حائل')
        self.assertEqual(urls, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('browser dead', warnings[0])

    def test_agent_exception_surfaces_as_a_warning(self):
        with mock.patch.object(agent, 'run_browse_agent',
                               side_effect=RuntimeError('no chromium')):
            urls, warnings = city_regulations.discover_city_regulation_urls(
                'hail', 'حائل')
        self.assertEqual(urls, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('no chromium', warnings[0])


if __name__ == '__main__':
    unittest.main()
