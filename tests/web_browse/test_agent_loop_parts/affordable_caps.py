"""Token-cap retries and fatal cancellation for browse-agent loops."""

import threading
import unittest
from unittest import mock

from tests.web_browse.test_agent_loop import (
    _FINAL_TEXT,
    _fn_response,
    _patched_pipeline,
    _scripted_chat,
    _text_response,
    agent,
)


class RunBrowseAgentAffordableCapTests(unittest.TestCase):
    def test_provider_affordability_quote_retries_same_round_at_allowed_cap(self):
        calls = []
        chat_impl = _scripted_chat([
            {'error': {
                'provider_message': 'can only afford 24000 tokens',
                'message': 'the requested output cap exceeds the current allowance',
            }},
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent(
                'task', max_steps=2, max_tokens=64000)

        self.assertNotIn('error', result)
        self.assertEqual([call['kwargs']['max_tokens'] for call in calls],
                         [64000, 24000])
        self.assertEqual(
            result['choices'][0]['message']['content'], _FINAL_TEXT)

    def test_fatal_balance_error_with_affordability_quote_stops_immediately(self):
        calls = []
        fatal = {'error': {
            'fatal': True,
            'provider_message': 'can only afford 24000 tokens',
            'message': 'رصيد غير كافٍ',
            'error_code': 'INSUFFICIENT_CREDITS',
            'http_status': 402,
        }}
        chat_impl = _scripted_chat([fatal, _text_response()], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent(
                'task', max_steps=24, max_tokens=64000)

        self.assertEqual(result['error']['error_code'], 'INSUFFICIENT_CREDITS')
        self.assertTrue(result['error']['fatal'])
        self.assertEqual([call['kwargs']['max_tokens'] for call in calls], [64000])

    def test_parallel_balance_cancellation_stops_before_next_round(self):
        calls = []
        cancel_event = threading.Event()
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)

        def fatal_sibling():
            cancel_event.set()

        with _patched_pipeline(chat_impl), \
                mock.patch.object(agent, '_execute_tool',
                                  side_effect=lambda *_a, **_kw: (
                                      fatal_sibling() or {'ok': True})):
            result = agent.run_browse_agent(
                'task', max_steps=24, cancel_event=cancel_event)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result['error']['message'],
                         'cancelled_after_parallel_fatal_refusal')
