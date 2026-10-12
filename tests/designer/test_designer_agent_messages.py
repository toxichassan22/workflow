import json
import unittest
from unittest.mock import Mock, patch


class OpenRouterMessagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.module = app

    def _posted(self, payload, status=200):
        response = Mock()
        response.status_code = status
        response.text = json.dumps(payload, ensure_ascii=False)
        response.json.return_value = payload
        return response

    def test_messages_round_trip_with_tool_calls(self):
        """A two-step tool loop: call -> tool_call -> tool result -> final."""
        first = self._posted({'choices': [{'message': {
            'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'c1', 'type': 'function',
                            'function': {'name': 'get_slides',
                                         'arguments': '{"ids": ["s_1"]}'}}],
        }}], 'usage': {'total_tokens': 10}})
        second = self._posted({'choices': [{'message': {
            'role': 'assistant', 'content': '{"kind":"reply","message":"تم"}',
        }}], 'usage': {'total_tokens': 4}})
        with patch.object(self.module.requests, 'post', side_effect=[first, second]) as post:
            messages = [{'role': 'system', 'content': 'sys'},
                        {'role': 'user', 'content': 'عدل'}]
            raw1 = self.module.call_openrouter_messages(
                messages, tools=[{'type': 'function', 'function': {'name': 'get_slides'}}],
                usage_ctx={})
            step1 = self.module.openrouter_response_message(raw1)
            self.assertEqual(step1['tool_calls'][0]['name'], 'get_slides')
            self.assertEqual(step1['tool_calls'][0]['arguments'], {'ids': ['s_1']})
            self.assertEqual(step1['usage']['total_tokens'], 10)

            messages.append(self.module.openrouter_assistant_tool_message(step1))
            messages.append(self.module.openrouter_tool_result_message(
                step1['tool_calls'][0], {'slides': [{'id': 's_1'}]}))
            raw2 = self.module.call_openrouter_messages(messages, usage_ctx={})
            step2 = self.module.openrouter_response_message(raw2)
            self.assertEqual(step2['content'], '{"kind":"reply","message":"تم"}')

            # Second request carried the assistant tool_calls + tool message verbatim.
            sent_messages = post.call_args_list[1].kwargs['json']['messages']
            self.assertEqual(sent_messages[-2]['tool_calls'][0]['id'], 'c1')
            self.assertEqual(sent_messages[-1]['role'], 'tool')
            self.assertEqual(sent_messages[-1]['tool_call_id'], 'c1')

    def test_json_schema_response_format_is_passed_through(self):
        schema = {'type': 'json_schema', 'json_schema': {
            'name': 'agent_turn', 'strict': True,
            'schema': {'type': 'object', 'properties': {'kind': {'type': 'string'}}}}}
        with patch.object(self.module.requests, 'post',
                          return_value=self._posted({'choices': [{'message': {'content': '{}'}}]})) as post:
            self.module.call_openrouter_messages(
                [{'role': 'user', 'content': 'x'}], response_format=schema, usage_ctx={})
            sent = post.call_args.kwargs['json']
            self.assertEqual(sent['response_format'], schema)
            self.assertEqual(sent['messages'], [{'role': 'user', 'content': 'x'}])

    def test_reasoning_fills_empty_content(self):
        raw = {'choices': [{'message': {'content': '', 'reasoning': 'because'}}]}
        result = self.module.openrouter_response_message(raw)
        self.assertEqual(result['content'], 'because')

    def test_provider_error_raises(self):
        with self.assertRaises(RuntimeError):
            self.module.openrouter_response_message({'error': {'message': 'boom'}})
        with self.assertRaises(RuntimeError):
            self.module.openrouter_response_message({'choices': []})

    def test_tool_arguments_string_or_dict(self):
        raw = {'choices': [{'message': {'tool_calls': [
            {'id': 'a', 'function': {'name': 'f', 'arguments': '{"x": 1}'}},
            {'id': 'b', 'function': {'name': 'g', 'arguments': {'y': 2}}},
            {'id': 'c', 'function': {'name': 'h', 'arguments': 'not-json'}},
        ]}}]}
        calls = self.module.openrouter_response_message(raw)['tool_calls']
        self.assertEqual([c['arguments'] for c in calls], [{'x': 1}, {'y': 2}, {}])


if __name__ == '__main__':
    unittest.main()
