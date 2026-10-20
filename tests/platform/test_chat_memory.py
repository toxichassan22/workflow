"""The shared conversation memory every assistant chat runs on.

The chats used to carry a fixed slice of the conversation — eight turns in the
plans popup, ten in the land chat, ten in the designer chat — so the assistant
contradicted what the client had just agreed and "forgot" what it was supposed
to do. This suite guards the memory contract: the whole conversation travels,
the newest turns stay verbatim inside the input budget, and the older ones are
folded into a digest that keeps the CLIENT's own words.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CHAT_MODULE_DIR = ROOT / 'modules' / 'chat'
if str(CHAT_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(CHAT_MODULE_DIR))

import chat_memory  # noqa: E402


class ChatMemoryTests(unittest.TestCase):
    def test_a_short_conversation_stays_verbatim_and_keeps_no_digest(self):
        turns = [
            {'role': 'user', 'content': 'الشريحة 8 فيها مشكلة'},
            {'role': 'assistant', 'content': 'ما هي المشكلة تحديدًا؟'},
        ]
        context = chat_memory.build_context(turns)
        self.assertEqual(context['memory'], '')
        self.assertEqual(context['folded'], 0)
        self.assertEqual(len(context['verbatim']), 2)

    def test_the_whole_conversation_travels_inside_the_token_budget(self):
        turns = [{'role': 'user', 'content': 'رسالة %d' % index} for index in range(400)]
        context = chat_memory.build_context(turns)
        self.assertEqual(len(context['verbatim']), chat_memory.CHAT_MEMORY_VERBATIM_TURNS)
        self.assertEqual(context['folded'], 400 - chat_memory.CHAT_MEMORY_VERBATIM_TURNS)
        # Nothing is lost: the digest carries the turns the verbatim window
        # could not hold, and the newest turns stay word-for-word.
        self.assertIn('رسالة 0', context['memory'])
        self.assertEqual(context['verbatim'][-1]['content'], 'رسالة 399')
        self.assertNotIn('رسالة 399', context['memory'])

    def test_the_clients_own_words_survive_the_folding(self):
        turns = []
        for index in range(120):
            turns.append({'role': 'assistant', 'content': 'رد مساعد طويل ' + 'ط' * 900})
            turns.append({'role': 'user', 'content': 'طلب العميل %d' % index})
        context = chat_memory.build_context(turns)
        self.assertTrue(context['memory'])
        # The instruction survives even when the assistant chatter around it is
        # dropped — an instruction is a contract, a reply is disposable.
        self.assertIn('طلب العميل 0', context['memory'])

    def test_the_digest_stays_bounded(self):
        turns = [{'role': 'user', 'content': 'س' * 4000} for _ in range(500)]
        context = chat_memory.build_context(turns)
        self.assertLessEqual(len(context['memory']), chat_memory.CHAT_MEMORY_DIGEST_CHARS)

    def test_a_stale_client_snapshot_never_drops_the_stored_turns(self):
        stored = [
            {'role': 'user', 'content': 'الأولى'},
            {'role': 'assistant', 'content': 'الثانية'},
            {'role': 'user', 'content': 'الثالثة'},
        ]
        incoming = [{'role': 'user', 'content': 'الثالثة'}]
        merged = chat_memory.merge_turns(stored, incoming)
        self.assertEqual([turn['content'] for turn in merged],
                         ['الأولى', 'الثانية', 'الثالثة'])
        # A client that only knows the newest turn still keeps the whole thread.
        merged = chat_memory.merge_turns(stored, [{'role': 'user', 'content': 'الرابعة'}])
        self.assertEqual(len(merged), 4)

    def test_the_prompt_carries_the_memory_the_agreements_and_the_turns(self):
        context = chat_memory.build_context(
            [{'role': 'user', 'content': 'السكن في الطابق الأول'}],
            memory='العميل يفضّل السكن في الطابق الأول',
            decisions=['السكن في الطابق الأول'])
        block = chat_memory.prompt_block(context)
        self.assertIn('ذاكرة المحادثة', block)
        self.assertIn('ما اتُّفق عليه', block)
        self.assertIn('السكن في الطابق الأول', block)
        self.assertIn('آخر الرسائل', block)

    def test_the_model_may_rewrite_the_memory_it_carries_forward(self):
        context = chat_memory.build_context([{'role': 'user', 'content': 'سؤال'}])
        chat_memory.apply_model_memory(context, {
            'memory': 'ملخص جديد للجلسة',
            'decisions': ['قرار أول', 'قرار أول', '  ', 'قرار ثانٍ'],
        })
        self.assertEqual(context['memory'], 'ملخص جديد للجلسة')
        self.assertEqual(context['decisions'], ['قرار أول', 'قرار ثانٍ'])

    def test_the_slide_reference_of_a_turn_survives_the_digest(self):
        turns = [{'role': 'user', 'content': 'الشريحة 3', 'slides': [3]}]
        context = chat_memory.build_context(turns, budget_tokens=1)
        self.assertIn('[شرائح: 3]', context['memory'])

    def test_the_memory_never_calls_a_provider(self):
        source = (CHAT_MODULE_DIR / 'chat_memory.py').read_text(encoding='utf-8')
        self.assertNotIn('call_openrouter_chat', source)
        self.assertNotIn('call_text_chat', source)
        self.assertNotIn('requests.', source)


if __name__ == '__main__':
    unittest.main()
