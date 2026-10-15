"""Summary-chat contract module — the pure prompt/normalize/ops helpers.

The interactive market-summary chat (plan: docs/plans/market stude/plan.md)
rests on modules/market/market_study_parts/04_summary_chat.py: a discuss
prompt that may propose targeted ops, a browse-agent research prompt, the
ops whitelist (set_axis/set_swot/set_decision/add_sources), the pure
apply_summary_ops transform and the staleness map. Everything is pure —
no Flask, no db, no network — so this suite imports market_study directly.

Run like every other suite::

    python -m unittest tests.market.test_summary_chat_module
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_study


def _state():
    return {
        'summary': {
            item['key']: f'نص محور {item["key"]}'
            for item in market_study.SUMMARY_SECTIONS
        },
        'swot': {item['key']: f'خانة {item["key"]}'
                 for item in market_study.SWOT_SECTIONS},
        'decision': 'فرصة واعدة بشروط',
        'sources': [
            {'id': 's1', 'name': 'سكني', 'url': 'https://sakani.sa/report',
             'data_date': '2025-06', 'accessed_at': '2026-01-01',
             'reliability': '', 'note': ''},
        ],
        'one_block_summary': 'فقرة تنفيذية حالية',
    }


class SummaryChatAxesTests(unittest.TestCase):

    def test_axes_list_general_first_then_section_order(self):
        axes = market_study.summary_chat_axes()
        self.assertEqual(len(axes), len(market_study.SUMMARY_SECTIONS) + 1)
        self.assertEqual(axes[0], {'key': 'general', 'label': 'عام'})
        self.assertEqual([item['key'] for item in axes[1:]],
                         [item['key'] for item in market_study.SUMMARY_SECTIONS])
        self.assertEqual(axes[1]['label'], market_study.SUMMARY_SECTIONS[0]['label'])

    def test_axes_english_labels_when_offer_en(self):
        axes = market_study.summary_chat_axes(offer_lang='en')
        self.assertEqual(axes[0]['label'], 'General')
        self.assertEqual(axes[1]['label'], 'Market Definition')
        self.assertEqual(axes[-1]['label'], 'Risks')


class SummaryChatPromptTests(unittest.TestCase):

    def test_system_prompt_states_the_chat_rules(self):
        system = market_study.build_summary_chat_system()
        self.assertIn('لا تدّعِ', system)              # never claims an edit applied
        self.assertIn('needs_research', system)        # research trigger
        self.assertIn('reply', system)
        self.assertNotIn('http', system.split('reply نص عادي')[0])  # no urls in rules

    def test_system_prompt_english_directive(self):
        self.assertIn('professional English',
                      market_study.build_summary_chat_system(offer_lang='en'))
        self.assertNotIn('professional English',
                         market_study.build_summary_chat_system())

    def test_turn_prompt_carries_context_and_output_shape(self):
        state = _state()
        state['summary']['supply'] = 'المعروض الحالي مرتفع'
        history = [{'role': 'user', 'content': 'ما رأيك؟'},
                   {'role': 'assistant', 'content': 'العرض يحتاج تحديثًا'}]
        prompt = market_study.build_summary_chat_turn_prompt(
            {'projectName': 'مشروع الاختبار', 'district': 'حي النرجس', 'city': 'الرياض'},
            'supply', 'حدّث محور العرض', history, state)
        self.assertIn('حي النرجس', prompt)             # project input block
        self.assertIn('supply', prompt)                # the axis key
        self.assertIn('المعروض الحالي مرتفع', prompt)  # current axis text
        self.assertIn('market_definition', prompt)     # other-axis index
        self.assertIn('سكني', prompt)                  # sources table
        self.assertIn('ما رأيك؟', prompt)              # history
        self.assertIn('حدّث محور العرض', prompt)       # the message
        self.assertIn('"needs_research"', prompt)      # JSON output shape
        self.assertIn('"ops"', prompt)
        self.assertIn('"axis"', prompt)                # model-detected axis
        self.assertIn('"needs_clarification"', prompt) # ambiguity contract
        for option in market_study.DECISION_OPTIONS:   # decision enum listed
            self.assertIn(option, prompt)

    def test_turn_prompt_general_axis_shows_whole_summary(self):
        state = _state()
        prompt = market_study.build_summary_chat_turn_prompt(
            {}, market_study.SUMMARY_CHAT_AXIS_GENERAL, 'قيّم الملخص', [], state)
        self.assertIn('فقرة تنفيذية حالية', prompt)    # one_block stands in
        self.assertIn('supply', prompt)                # every axis indexed

    def test_research_prompt_carries_queries_and_browse_rules(self):
        prompt = market_study.build_summary_chat_research_prompt(
            {'city': 'جدة'}, 'demand', 'ابحث عن الطلب', [], _state(),
            ['طلب المكاتب جدة 2025', 'إشغال المكاتب حي المشروع'])
        self.assertIn('طلب المكاتب جدة 2025', prompt)
        self.assertIn('إشغال المكاتب حي المشروع', prompt)
        self.assertIn('"sources_add"', prompt)         # research output shape
        self.assertIn('بحث جوجل الأصلي', prompt)       # native search required
        self.assertNotIn('افتح الصفحات', prompt)       # zero page opens here
        self.assertIn('فترة البيانات', prompt)         # period lock restated

    def test_consolidate_prompt_regenerates_only_flagged_keys(self):
        prompt = market_study.build_summary_consolidate_prompt(
            _state(), ['one_block', 'decision'])
        self.assertIn('"one_block_summary"', prompt)
        self.assertIn('"decision"', prompt)
        self.assertNotIn('"swot":', prompt)            # unflagged stays out
        self.assertIn('بلا بحث', prompt)               # no-browse declared
        self.assertIn('نص محور supply', prompt)        # final axes carried

    def test_project_input_block_includes_the_full_project_facts(self):
        block = market_study._project_input_block({
            'projectName': 'مشروع', 'city': 'جدة',
            'projectFacts': '### الموقع\n- الحي: النرجس\n\n### بيانات إضافية\n- ملاحظة: قاعة مائية',
        })
        self.assertIn('جدة', block)                    # compact inputs stay
        self.assertIn('سياق ملف المشروع الكامل', block)
        self.assertIn('قاعة مائية', block)             # all-sections facts
        self.assertNotIn('سياق ملف المشروع الكامل',
                         market_study._project_input_block({'city': 'جدة'}))


class NormalizeChatReplyTests(unittest.TestCase):

    def test_parsed_dict_normalizes(self):
        result = market_study.normalize_summary_chat_reply({
            'reply': 'الرد', 'needs_research': True,
            'queries': ['q1', ' ', 'q2'],
            'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'v'}]})
        self.assertEqual(result['reply'], 'الرد')
        self.assertTrue(result['needs_research'])
        self.assertEqual(result['queries'], ['q1', 'q2'])
        self.assertEqual(len(result['ops']), 1)

    def test_raw_json_string_parses(self):
        raw = json.dumps({'reply': 'جواب', 'ops': []}, ensure_ascii=False)
        self.assertEqual(market_study.normalize_summary_chat_reply(raw)['reply'], 'جواب')

    def test_fenced_and_prose_wrapped_json_parses(self):
        fenced = 'إليك الرد:\n```json\n{"reply": "داخل سياج", "ops": []}\n```\nشكرًا'
        self.assertEqual(market_study.normalize_summary_chat_reply(fenced)['reply'],
                         'داخل سياج')
        prose = 'مقدمة قبل {"reply": "وسط النص"} تعليق بعد'
        self.assertEqual(market_study.normalize_summary_chat_reply(prose)['reply'],
                         'وسط النص')

    def test_garbage_raises_arabic_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            market_study.normalize_summary_chat_reply('لا JSON هنا إطلاقًا')
        self.assertTrue(str(ctx.exception))
        with self.assertRaises(ValueError):
            market_study.normalize_summary_chat_reply({'ops': []})   # no reply
        with self.assertRaises(ValueError):
            market_study.normalize_summary_chat_reply(['not', 'a', 'dict'])

    def test_needs_research_string_coercion(self):
        result = market_study.normalize_summary_chat_reply(
            {'reply': 'ر', 'needs_research': 'false'})
        self.assertFalse(result['needs_research'])

    def test_reply_axis_and_clarification_normalize(self):
        result = market_study.normalize_summary_chat_reply(
            {'reply': 'سؤال', 'axis': 'demand', 'needs_clarification': 'true'})
        self.assertEqual(result['axis'], 'demand')
        self.assertTrue(result['needs_clarification'])
        # A key outside the axis whitelist folds back to the general thread.
        result = market_study.normalize_summary_chat_reply(
            {'reply': 'سؤال', 'axis': 'invented_axis'})
        self.assertEqual(result['axis'], market_study.SUMMARY_CHAT_AXIS_GENERAL)
        self.assertFalse(result['needs_clarification'])

    def test_research_normalizes_sources_add(self):
        result = market_study.normalize_summary_chat_research({
            'reply': '', 'ops': [{'op': 'set_decision', 'value': 'فرصة قوية'}],
            'sources_add': [
                {'name': 'إيجار', 'url': 'https://ejar.sa/x', 'data_date': '2025',
                 'note': 'ملاحظة', 'reliability': 'رسمي'},
                {'name': '', 'url': ''},   # empty row drops
            ]})
        self.assertEqual(result['reply'], '')          # empty reply tolerated
        self.assertEqual(len(result['ops']), 1)
        self.assertEqual(len(result['sources_add']), 1)
        self.assertEqual(result['sources_add'][0]['url'], 'https://ejar.sa/x')
        with self.assertRaises(ValueError):
            market_study.normalize_summary_chat_research('مجرد نص')


class ValidateSummaryOpsTests(unittest.TestCase):

    def test_valid_ops_of_each_kind_survive(self):
        ops = [
            {'op': 'set_axis', 'key': 'supply', 'value': 'نص جديد'},
            {'op': 'set_swot', 'key': 'strengths', 'value': 'قوة جديدة'},
            {'op': 'set_decision', 'value': 'فرصة قوية'},
            {'op': 'add_sources', 'rows': [
                {'name': 'مصدر', 'url': 'https://a.sa/p', 'data_date': '2025'}]},
        ]
        kept, rejected = market_study.validate_summary_ops(ops)
        self.assertEqual(len(kept), 4)
        self.assertEqual(rejected, [])
        self.assertEqual(kept[0]['value'], 'نص جديد')

    def test_bad_entries_drop_into_rejected_keeping_good_ops(self):
        ops = [
            {'op': 'set_axis', 'key': 'supply', 'value': 'يبقى'},
            {'op': 'set_axis', 'key': 'no_such_axis', 'value': 'x'},
            {'op': 'set_swot', 'key': 'strengthz', 'value': 'x'},
            {'op': 'set_decision', 'value': 'قرار مؤلف'},
            {'op': 'delete_axis', 'key': 'supply'},
            'مجرد نص',
            {'op': 'set_axis', 'key': 'demand', 'value': '   '},
        ]
        kept, rejected = market_study.validate_summary_ops(ops)
        self.assertEqual(kept, [{'op': 'set_axis', 'key': 'supply', 'value': 'يبقى'}])
        reasons = [item['reason'] for item in rejected]
        self.assertEqual(reasons, ['unknown_axis', 'unknown_swot_key',
                                   'unknown_decision', 'unknown_op',
                                   'not_object', 'empty_value'])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            market_study.validate_summary_ops({'op': 'set_axis'})
        with self.assertRaises(ValueError):
            market_study.validate_summary_ops('set_axis')

    def test_decision_accepts_english_twin_and_contained_member(self):
        kept, _ = market_study.validate_summary_ops(
            [{'op': 'set_decision', 'value': 'Strong opportunity'}])
        self.assertEqual(kept[0]['value'], 'فرصة قوية')
        kept, _ = market_study.validate_summary_ops(
            [{'op': 'set_decision', 'value': 'أرى أنها فرصة مرتفعة المخاطر'}])
        self.assertEqual(kept[0]['value'], 'فرصة مرتفعة المخاطر')

    def test_add_sources_caps_at_eight_and_drops_empty_rows(self):
        rows = [{'name': f'مصدر {i}', 'url': f'https://s.sa/{i}'} for i in range(10)]
        rows.append({'name': '', 'url': ''})
        kept, rejected = market_study.validate_summary_ops(
            [{'op': 'add_sources', 'rows': rows}])
        self.assertEqual(len(kept[0]['rows']), 8)
        self.assertEqual(rejected[0]['reason'], 'rows_over_limit')
        kept, rejected = market_study.validate_summary_ops(
            [{'op': 'add_sources', 'rows': [{'name': '', 'url': ''}]}])
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]['reason'], 'empty_rows')

    def test_text_values_stripped_of_icons_and_trimmed(self):
        kept, _ = market_study.validate_summary_ops(
            [{'op': 'set_axis', 'key': 'supply', 'value': 'عرض قوي ✅ ومتزايد'}])
        self.assertNotIn('✅', kept[0]['value'])
        self.assertIn('عرض قوي', kept[0]['value'])
        long_text = 'عرض قوي ' + ('س' * 7000)
        kept, _ = market_study.validate_summary_ops(
            [{'op': 'set_axis', 'key': 'supply', 'value': long_text}])
        self.assertLessEqual(len(kept[0]['value']), 6000)


class ApplySummaryOpsTests(unittest.TestCase):

    def test_apply_writes_each_field_and_reports_touched(self):
        state = _state()
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'set_axis', 'key': 'supply', 'value': 'نص العرض الجديد'},
            {'op': 'set_swot', 'key': 'weaknesses', 'value': 'ضعف جديد'},
            {'op': 'set_decision', 'value': 'فرصة قوية'},
        ])
        self.assertEqual(new_state['summary']['supply'], 'نص العرض الجديد')
        self.assertEqual(new_state['swot']['weaknesses'], 'ضعف جديد')
        self.assertEqual(new_state['decision'], 'فرصة قوية')
        self.assertEqual(touched, {'supply', 'weaknesses', 'decision'})
        # Pure: the input state is untouched.
        self.assertEqual(state['summary']['supply'], 'نص محور supply')
        self.assertEqual(state['decision'], 'فرصة واعدة بشروط')

    def test_apply_add_sources_dedupes_by_url(self):
        state = _state()
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'add_sources', 'rows': [
                {'name': 'سكني مكرر', 'url': 'https://sakani.sa/report'},   # dupe
                {'name': 'جديد', 'url': 'https://rega.gov.sa/x',
                 'data_date': '2025-03'}]},
        ])
        self.assertEqual(len(new_state['sources']), 2)
        self.assertEqual(new_state['sources'][1]['name'], 'جديد')
        self.assertEqual(touched, {'sources'})
        self.assertEqual(len(state['sources']), 1)     # input untouched

    def test_identical_rewrite_is_not_touched(self):
        state = _state()
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'set_axis', 'key': 'supply', 'value': 'نص محور supply'}])
        self.assertEqual(touched, set())
        self.assertEqual(new_state['summary']['supply'], 'نص محور supply')

    def test_apply_rejects_bad_ops_silently(self):
        state = _state()
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'set_axis', 'key': 'bogus', 'value': 'x'},
            {'op': 'hack', 'key': 'decision', 'value': 'x'}])
        self.assertEqual(touched, set())
        self.assertNotIn('bogus', new_state['summary'])


class SummaryOpsStaleTests(unittest.TestCase):

    def test_stale_matrix(self):
        # Any axis write stales the paragraph, the decision and SWOT.
        self.assertEqual(market_study.summary_ops_stale({'supply'}),
                         {'one_block': True, 'decision': True, 'swot': True})
        # Swot/decision writes stale the paragraph that quotes them.
        self.assertEqual(market_study.summary_ops_stale({'strengths'}),
                         {'one_block': True})
        self.assertEqual(market_study.summary_ops_stale({'decision'}),
                         {'one_block': True})
        # New sources alone stale nothing.
        self.assertEqual(market_study.summary_ops_stale({'sources'}), {})
        self.assertEqual(market_study.summary_ops_stale(set()), {})

    def test_apply_then_stale_round_trip(self):
        _new_state, touched = market_study.apply_summary_ops(_state(), [
            {'op': 'set_axis', 'key': 'risks', 'value': 'مخاطر جديدة'},
            {'op': 'add_sources', 'rows': [{'name': 'مصدر', 'url': 'https://x.sa'}]}])
        self.assertEqual(market_study.summary_ops_stale(touched),
                         {'one_block': True, 'decision': True, 'swot': True})


if __name__ == '__main__':
    unittest.main()
