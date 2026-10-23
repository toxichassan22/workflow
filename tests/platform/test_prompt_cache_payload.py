"""Stable prompt prefixes are marked only where the provider expects it.

Anthropic receives the explicit cache marker; OpenAI and Gemini keep their
automatic prefix caching and must not get a foreign marker. The disable flag
restores the previous payload byte for byte.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application


class PromptCachePayloadTests(unittest.TestCase):
    def test_anthropic_system_prompt_gets_an_ephemeral_marker(self):
        content = application._cached_system_content('stable rules', 'anthropic/claude-x')
        self.assertEqual(content[0]['text'], 'stable rules')
        self.assertEqual(content[0]['cache_control'], {'type': 'ephemeral'})

    def test_openai_and_gemini_keep_the_plain_string(self):
        for model in ('openai/gpt-6.1-sol', 'google/gemini-4-argon'):
            self.assertEqual(
                application._cached_system_content('stable rules', model), 'stable rules')

    def test_disable_flag_keeps_every_provider_plain(self):
        with patch.dict(os.environ, {'PROMPT_CACHE_ENABLED': '0'}):
            self.assertEqual(
                application._cached_system_content('stable rules', 'anthropic/claude-x'),
                'stable rules')

    def test_messages_system_block_is_marked_without_mutating_the_caller(self):
        messages = [
            {'role': 'system', 'content': 'stable rules'},
            {'role': 'user', 'content': 'edit'},
        ]
        cached = application._cache_system_messages(messages, 'anthropic/claude-x')
        self.assertEqual(cached[0]['content'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(messages[0]['content'], 'stable rules')

    def test_non_anthropic_messages_are_untouched(self):
        messages = [
            {'role': 'system', 'content': 'stable rules'},
            {'role': 'user', 'content': 'edit'},
        ]
        self.assertIs(
            application._cache_system_messages(messages, 'openai/gpt-6.1-sol'), messages)


if __name__ == '__main__':
    unittest.main()
