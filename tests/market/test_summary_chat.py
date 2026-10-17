"""Interactive market-summary chat — contract suite (plan board task A4).

The one-shot market summary gains a per-axis chat session on top of it: each
turn is a market job (``kind='summary_chat'``) that answers in the user's
language, optionally runs a bounded live browse (phase B through
``_browse_agent_call``) and may return a *proposal* — a whitelist of ops
(``set_axis`` / ``set_swot`` / ``set_decision`` / ``add_sources``) shown to the
user, never applied server-side. Applying is client-side selection UX; editing
an axis marks ``one_block_summary`` / ``decision`` / ``swot`` stale until a
``summary_consolidate`` job regenerates only the flagged dependents — it never
browses. Once the market section's generated content is approved
(``section_statuses['section-market-study'] == 'approved'``), op-producing
turns are refused with ``SUMMARY_APPROVAL_LOCKED`` while pure discussion keeps
answering.

Written against the contracts in ``docs/plans/market stude/plan.md``: module
helpers live in ``market_study`` (part ``04_summary_chat.py``) and the
executors in the app namespace (part ``18f_summary_chat.py``). Zero network —
the text model, the browse agent and the URL probe are mocked; the chat model
defaults to ``GEMINI_TEXT_MODEL`` (Gemini 4 Argon) with ``MARKET_CHAT_MODEL``
as the owner override. The client never picks an axis: the model detects it
and echoes it back, and an ambiguous message returns a clarification question
instead of an edit.

Run like every other suite — one suite per process, PYTHONPATH=repo root::

    python -m unittest tests.market.test_summary_chat
"""

import copy
import json
import os
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_MODULES = ROOT / 'modules'
if _MODULES.is_dir():
    for _dirpath, _dirnames, _filenames in os.walk(_MODULES):
        if any(_f.endswith('.py') for _f in _filenames) and _dirpath not in sys.path:
            sys.path.insert(0, _dirpath)
    del _dirpath, _dirnames, _filenames

import auth
import db
import market_study


def _chat_state():
    """A summary session state as the executors/builders see it."""
    return {
        'summary': {
            item['key']: f'نص {item["key"]} الحالي' for item in market_study.SUMMARY_SECTIONS
        },
        'swot': {
            item['key']: f'خانة {item["key"]} الحالية' for item in market_study.SWOT_SECTIONS
        },
        'decision': market_study.DECISION_OPTIONS[0],
        'one_block_summary': 'الفقرة التنفيذية الحالية',
        'sources': [
            {'name': 'مؤشر الإيجار التفصيلي',
             'url': 'https://sakani.sa/reports-and-data',
             'data_date': '2025-06'},
        ],
    }


def _payload():
    return {
        'projectName': 'برج الاختبار',
        'projectType': 'سكني',
        'city': 'جدة',
        'district': 'النرجس',
        'resolvedRadiusKm': 10,
        'dataPeriodBounds': {'from': '2024-10-14', 'to': '2026-10-14'},
    }


def _chat_result(payload, citations=()):
    """OpenRouter-shaped reply whose message content is a JSON object."""
    message = {'role': 'assistant', 'content': json.dumps(payload, ensure_ascii=False)}
    if citations:
        message['annotations'] = [
            {'url_citation': {'url': url, 'title': 'صفحة مصدر', 'content': 'نص مسترجع'}}
            for url in citations]
    return {
        'choices': [{'finish_reason': 'stop', 'message': message}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
    }


class SummaryChatAxesTests(unittest.TestCase):
    """summary_chat_axes — the thread list the UI renders."""

    def test_general_constant_and_axis_order(self):
        self.assertEqual(market_study.SUMMARY_CHAT_AXIS_GENERAL, 'general')
        axes = market_study.summary_chat_axes()
        self.assertEqual(
            [axis['key'] for axis in axes],
            ['general'] + [item['key'] for item in market_study.SUMMARY_SECTIONS])
        for axis in axes:
            self.assertIsInstance(axis.get('label'), str)
            self.assertTrue(axis['label'].strip())

    def test_english_variant_labels(self):
        axes = market_study.summary_chat_axes(offer_lang='en')
        self.assertEqual(
            [axis['key'] for axis in axes],
            ['general'] + [item['key'] for item in market_study.SUMMARY_SECTIONS])
        for axis in axes:
            label = str(axis.get('label') or '')
            self.assertTrue(label.strip())
            self.assertIsNone(re.search(r'[؀-ۿ]', label),
                              f'English axis label is not English: {label!r}')


class SummaryChatPromptTests(unittest.TestCase):
    """The prompt builders carry the chat contract into the model call."""

    def test_system_prompt_describes_the_output_contract(self):
        system = market_study.build_summary_chat_system()
        self.assertIsInstance(system, str)
        self.assertTrue(system.strip())
        turn = market_study.build_summary_chat_turn_prompt(
            _payload(), 'supply', 'حدّث أرقام العرض', [], _chat_state())
        combined = system + '\n' + turn
        # The op vocabulary and the reply shape must be named somewhere the
        # model reads them, or it cannot emit a valid proposal.
        for token in ('reply', 'ops', 'set_axis', 'set_swot', 'set_decision',
                      'add_sources'):
            self.assertIn(token, combined)

    def test_turn_prompt_carries_axis_context_history_and_sources(self):
        history = [{'role': 'user', 'content': 'm00'}, {'role': 'assistant', 'content': 'm01'}]
        prompt = market_study.build_summary_chat_turn_prompt(
            _payload(), 'supply', 'حدّث أرقام العرض بالربع الأخير', history, _chat_state())
        self.assertIn('النرجس', prompt)
        self.assertIn('supply', prompt)
        self.assertIn('نص supply الحالي', prompt)
        # Other axes ride as a first-lines index — another axis's own line
        # must appear while its key is not the axis under discussion.
        self.assertIn('نص demand الحالي', prompt)
        self.assertIn('m00', prompt)
        self.assertIn('m01', prompt)
        self.assertIn('حدّث أرقام العرض بالربع الأخير', prompt)
        self.assertIn('https://sakani.sa/reports-and-data', prompt)

    def test_research_prompt_carries_queries_and_scope(self):
        queries = ['إيجار المتر حي النرجس 2025', 'مؤشر سكني التفصيلي للوحدات']
        prompt = market_study.build_summary_chat_research_prompt(
            _payload(), 'supply', 'ابحث عن الإيجارات', [], _chat_state(), queries)
        for query in queries:
            self.assertIn(query, prompt)
        self.assertIn('النرجس', prompt)

    def test_consolidate_prompt_names_flagged_dependents_and_state(self):
        prompt = market_study.build_summary_consolidate_prompt(
            _chat_state(), {'one_block': True, 'swot': True})
        self.assertIn('one_block', prompt)
        self.assertIn('swot', prompt)
        # Regeneration must rest on the final axes and the existing sources.
        self.assertIn('نص supply الحالي', prompt)
        self.assertIn('https://sakani.sa/reports-and-data', prompt)


class SummaryChatNormalizeTests(unittest.TestCase):
    """normalize_summary_chat_reply / _research parse the model JSON."""

    def test_plain_json_reply(self):
        raw = json.dumps({
            'reply': 'رد المساعد',
            'needs_research': True,
            'queries': ['استعلام'],
            'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'v'}],
        }, ensure_ascii=False)
        out = market_study.normalize_summary_chat_reply(raw)
        self.assertEqual(out['reply'], 'رد المساعد')
        self.assertIs(out['needs_research'], True)
        self.assertEqual(out['queries'], ['استعلام'])
        self.assertEqual(len(out['ops']), 1)

    def test_fenced_json_reply(self):
        raw = '```json\n{"reply": "محاط بسياج", "ops": []}\n```'
        out = market_study.normalize_summary_chat_reply(raw)
        self.assertEqual(out['reply'], 'محاط بسياج')

    def test_prose_wrapped_json_reply(self):
        raw = 'إليك الرد:\n{"reply": "داخل نص", "needs_research": false}\nانتهى.'
        out = market_study.normalize_summary_chat_reply(raw)
        self.assertEqual(out['reply'], 'داخل نص')

    def test_reply_defaults_when_optional_fields_missing(self):
        out = market_study.normalize_summary_chat_reply('{"reply": "فقط"}')
        self.assertEqual(out['reply'], 'فقط')
        self.assertFalse(out['needs_research'])
        self.assertEqual(out['queries'], [])
        self.assertEqual(out['ops'], [])

    def test_garbage_raises_arabic_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            market_study.normalize_summary_chat_reply('لا JSON هنا إطلاقًا')
        self.assertTrue(str(ctx.exception).strip())
        self.assertIsNotNone(re.search(r'[؀-ۿ]', str(ctx.exception)),
                             'the error reason must be Arabic')

    def test_non_object_json_is_malformed(self):
        with self.assertRaises(ValueError):
            market_study.normalize_summary_chat_reply('[1, 2, 3]')

    def test_research_reply_keeps_sources_add(self):
        raw = json.dumps({
            'reply': 'بعد البحث',
            'ops': [],
            'sources_add': [
                {'name': 'مؤشر', 'url': 'https://a.sa/1', 'data_date': '2025'},
            ],
        }, ensure_ascii=False)
        out = market_study.normalize_summary_chat_research(raw)
        self.assertEqual(out['reply'], 'بعد البحث')
        self.assertEqual(len(out['sources_add']), 1)
        self.assertEqual(out['sources_add'][0]['url'], 'https://a.sa/1')


class SummaryChatOpsTests(unittest.TestCase):
    """The ops whitelist: validate, apply, and the staleness matrix."""

    @staticmethod
    def _validate(ops):
        """Normalize the validator return into (kept, rejected).

        The contract pins a kept list plus a returned ``rejected`` list; the
        container shape (tuple or dict) is the implementer's choice.
        """
        result = market_study.validate_summary_ops(ops)
        if isinstance(result, tuple):
            kept = result[0]
            rejected = result[1] if len(result) > 1 else []
        elif isinstance(result, dict):
            kept = (result.get('ops') or result.get('valid')
                    or result.get('kept') or [])
            rejected = result.get('rejected') or []
        elif isinstance(result, list):
            kept, rejected = result, []
        else:
            raise AssertionError(f'unexpected validator return: {type(result)}')
        return list(kept), list(rejected)

    def test_validate_keeps_whitelist_ops(self):
        kept, rejected = self._validate([
            {'op': 'set_axis', 'key': 'supply', 'value': 'نص جديد'},
            {'op': 'set_swot', 'key': 'strengths', 'value': 'قوة جديدة'},
            {'op': 'set_decision', 'value': market_study.DECISION_OPTIONS[1]},
            {'op': 'add_sources', 'rows': [
                {'name': 'سكني', 'url': 'https://sakani.sa/x', 'data_date': '2025'}]},
        ])
        self.assertEqual(len(kept), 4)
        self.assertEqual(rejected, [])

    def test_validate_drops_unknown_ops_and_bad_keys(self):
        kept, rejected = self._validate([
            {'op': 'set_axis', 'key': 'supply', 'value': 'صالحة'},
            {'op': 'set_axis', 'key': 'not_an_axis', 'value': 'مفتاح سيئ'},
            {'op': 'set_axis', 'key': 'decision', 'value': 'مفتاح قديم'},
            {'op': 'set_swot', 'key': 'bogus_swot', 'value': 'x'},
            {'op': 'set_decision', 'value': 'قرار مختلق خارج القائمة'},
            {'op': 'delete_everything'},
            {'op': 'add_sources', 'rows': [
                {'name': 'مصدر', 'url': 'https://ok.sa/1', 'data_date': '2025'}]},
            'not-a-dict',
            {},
        ])
        kept_ops = [(op.get('op'), op.get('key')) for op in kept]
        self.assertIn(('set_axis', 'supply'), kept_ops)
        self.assertIn(('add_sources', None), kept_ops)
        self.assertEqual(len(kept), 2)
        self.assertGreaterEqual(len(rejected), 7)

    def test_validate_raises_only_on_non_list_input(self):
        with self.assertRaises((ValueError, TypeError)):
            market_study.validate_summary_ops('set_axis')
        with self.assertRaises((ValueError, TypeError)):
            market_study.validate_summary_ops({'op': 'set_axis'})

    def test_validate_caps_add_sources_rows_at_eight(self):
        rows = [{'name': f'مصدر {i}', 'url': f'https://src{i}.sa/p', 'data_date': '2025'}
                for i in range(12)]
        kept, _ = self._validate([{'op': 'add_sources', 'rows': rows}])
        total = sum(len(op.get('rows') or []) for op in kept if op.get('op') == 'add_sources')
        self.assertGreater(total, 0)
        self.assertLessEqual(total, 8)

    def test_validate_trims_long_values_and_strips_icons(self):
        kept, _ = self._validate([
            {'op': 'set_axis', 'key': 'supply', 'value': 'ن' * 7000}])
        self.assertEqual(len(kept), 1)
        self.assertLess(len(str(kept[0].get('value') or '')), 7000)

        kept, _ = self._validate([
            {'op': 'set_axis', 'key': 'supply', 'value': 'النص ✅ مع رمز'}])
        self.assertEqual(len(kept), 1)
        self.assertIn('النص', kept[0]['value'])
        self.assertNotIn('✅', kept[0]['value'])

    def test_apply_writes_ops_and_stays_pure(self):
        state = _chat_state()
        snapshot = copy.deepcopy(state)
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'set_axis', 'key': 'supply', 'value': 'العرض المحدّث'},
            {'op': 'set_swot', 'key': 'threats', 'value': 'تهديد جديد'},
            {'op': 'set_decision', 'value': market_study.DECISION_OPTIONS[2]},
        ])
        self.assertEqual(new_state['summary']['supply'], 'العرض المحدّث')
        self.assertEqual(new_state['swot']['threats'], 'تهديد جديد')
        self.assertEqual(new_state['decision'], market_study.DECISION_OPTIONS[2])
        self.assertTrue(touched)
        self.assertEqual(state, snapshot)

    def test_apply_add_sources_appends_and_dedupes_by_url(self):
        state = _chat_state()
        existing_url = state['sources'][0]['url']
        before = len(state['sources'])
        new_state, touched = market_study.apply_summary_ops(state, [
            {'op': 'add_sources', 'rows': [
                {'name': 'مكرر', 'url': existing_url, 'data_date': '2025'},
                {'name': 'مصدر جديد', 'url': 'https://new-source.sa/report', 'data_date': '2025-06'},
            ]},
        ])
        urls = [str(row.get('url') or '') for row in new_state['sources']]
        self.assertEqual(len(new_state['sources']), before + 1)
        self.assertEqual(len(urls), len({url.casefold() for url in urls}))
        self.assertIn('https://new-source.sa/report', urls)

    def test_stale_matrix(self):
        state = _chat_state()
        _, touched = market_study.apply_summary_ops(copy.deepcopy(state), [
            {'op': 'set_axis', 'key': 'supply', 'value': 'x'}])
        self.assertEqual(market_study.summary_ops_stale(touched),
                         {'one_block': True, 'decision': True, 'swot': True})

        _, touched = market_study.apply_summary_ops(copy.deepcopy(state), [
            {'op': 'set_swot', 'key': 'strengths', 'value': 'x'}])
        self.assertEqual(market_study.summary_ops_stale(touched), {'one_block': True})

        _, touched = market_study.apply_summary_ops(copy.deepcopy(state), [
            {'op': 'set_decision', 'value': market_study.DECISION_OPTIONS[2]}])
        self.assertEqual(market_study.summary_ops_stale(touched), {'one_block': True})

        _, touched = market_study.apply_summary_ops(copy.deepcopy(state), [
            {'op': 'add_sources', 'rows': [
                {'name': 'n', 'url': 'https://z.sa/1', 'data_date': '2025'}]}])
        self.assertEqual(market_study.summary_ops_stale(touched), {})


class _InlineThread:
    """threading.Thread stand-in that runs the target synchronously."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


class SummaryChatApiTests(unittest.TestCase):
    """Executors, routes and job dispatch for summary_chat / summary_consolidate."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-chat.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant(
                'Summary chat test', 'summary-chat@example.test', 'hash', 'summary-chat-test')
        cls.token = auth.create_token(
            cls.tenant, 'summary-chat@example.test',
            user_id=None, user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token}
        self.draft_id = uuid.uuid4().hex
        with self.app.app_context():
            db.save_project_draft(
                self.tenant, 'tenant-admin:' + self.tenant,
                {'project_name': 'برج الاختبار', 'city': 'جدة',
                 'draftId': self.draft_id,
                 'market_study_data': {'summary': {'supply': 'نص'}}},
                {'section-market-study': 'draft'}, draft_id=self.draft_id)
        for name in ('call_text_chat', 'call_openrouter_chat', 'call_text_chat_parallel',
                     'call_text_chat_stream', '_browse_agent_call'):
            mocked = patch.object(
                self.application_module, name,
                side_effect=AssertionError(f'unmocked provider call: {name}'))
            mocked.start()
            self.addCleanup(mocked.stop)
        billing = patch.object(
            self.application_module, '_require_billing_balance', return_value=None)
        billing.start()
        self.addCleanup(billing.stop)

    def _chat_data(self, **extra):
        data = {
            'draftId': self.draft_id,
            'axis': 'supply',
            'message': 'حدّث أرقام العرض بالربع الأخير',
            'research': 'auto',
            'history': [],
            'currentSummary': _chat_state()['summary'],
            'currentSources': _chat_state()['sources'],
            'currentSwot': _chat_state()['swot'],
            'decision': market_study.DECISION_OPTIONS[0],
            'oneBlockSummary': 'الفقرة الحالية',
            'city': 'جدة',
            'district': 'النرجس',
            'projectType': 'سكني',
            'dataPeriod': '24m',
        }
        data.update(extra)
        return data

    # -- executor contract ---------------------------------------------------

    def test_discuss_turn_returns_reply_and_null_proposal(self):
        module = self.application_module
        captured = {}

        def fake_chat(system, prompt, **kwargs):
            captured['prompt'] = prompt
            captured['kwargs'] = kwargs
            return _chat_result({
                'reply': 'رد نقاشي', 'needs_research': False, 'queries': [], 'ops': []})

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'owner-picked/chat-model'}), \
                patch.object(module, 'call_text_chat', side_effect=fake_chat):
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=self.tenant)

        self.assertTrue(result['success'], result)
        self.assertEqual(result['reply'], 'رد نقاشي')
        self.assertIsNone(result['proposal'])
        self.assertFalse(result.get('searchPerformed'))
        # The chat rides the owner-picked model — env-supplied, JSON output.
        self.assertEqual(captured['kwargs'].get('model'), 'owner-picked/chat-model')
        self.assertIn('json', str(captured['kwargs'].get('response_format')).lower())
        max_tokens = captured['kwargs'].get('max_tokens')
        self.assertTrue(max_tokens and 1000 <= int(max_tokens) <= 8000, max_tokens)
        usage_ctx = captured['kwargs'].get('usage_ctx') or {}
        self.assertEqual(usage_ctx.get('tenant_id'), self.tenant)
        self.assertEqual(usage_ctx.get('billing_flow'), 'market_summary')
        # The turn prompt carries the axis under discussion and the message.
        self.assertIn('النرجس', captured['prompt'])
        self.assertIn('حدّث أرقام العرض بالربع الأخير', captured['prompt'])

    def test_ops_turn_returns_proposal_without_applying(self):
        module = self.application_module

        def forbidden_browse(*args, **kwargs):
            raise AssertionError('browse must not run when needs_research is false')

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'هذا اقتراح',
                    'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'نص مقترح'}],
                })), \
                patch.object(module, '_browse_agent_call', side_effect=forbidden_browse):
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=self.tenant)

        self.assertTrue(result['success'], result)
        proposal = result['proposal']
        self.assertIsNotNone(proposal)
        self.assertTrue(any(
            op.get('op') == 'set_axis' and op.get('key') == 'supply'
            for op in proposal.get('ops') or []))
        self.assertIn('supply', proposal.get('touchedAxes') or [])
        self.assertIn('sourcesAdd', proposal)
        self.assertFalse(result.get('searchPerformed'))

    def test_turn_with_only_rejected_ops_is_a_discuss_turn(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'لا أستطيع تنفيذ ذلك',
                    'ops': [{'op': 'delete_summary'},
                            {'op': 'set_axis', 'key': 'bogus', 'value': 'x'}],
                })):
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=self.tenant)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['reply'], 'لا أستطيع تنفيذ ذلك')
        self.assertIsNone(result['proposal'])

    def test_missing_chat_model_env_defaults_to_argon(self):
        module = self.application_module
        captured = {}

        def fake_chat(system, prompt, **kwargs):
            captured['kwargs'] = kwargs
            return _chat_result({'reply': 'رد', 'ops': []})

        with self.app.app_context(), \
                patch.dict(os.environ) as env, \
                patch.object(module, 'call_text_chat', side_effect=fake_chat) as chat_mock:
            env.pop('MARKET_CHAT_MODEL', None)
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=self.tenant)
        self.assertTrue(chat_mock.called)
        self.assertTrue(result['success'], result)
        self.assertEqual(captured['kwargs'].get('model'), module.GEMINI_TEXT_MODEL)

    def test_auto_axis_echoes_the_model_detected_axis(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'رد عن الطلب', 'axis': 'demand', 'ops': []})):
            result = module._execute_market_summary_chat(
                self._chat_data(axis=''), tenant_id=self.tenant)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['axis'], 'demand')

    def test_auto_axis_rejects_a_hallucinated_axis_key(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'رد', 'axis': 'not_an_axis', 'ops': []})):
            result = module._execute_market_summary_chat(
                self._chat_data(axis=''), tenant_id=self.tenant)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['axis'], market_study.SUMMARY_CHAT_AXIS_GENERAL)

    def test_clarification_turn_never_edits_and_never_browses(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'هل تقصد العرض أم الطلب؟',
                    'needs_clarification': True,
                    'needs_research': True,
                    'queries': ['q'],
                    'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'v'}],
                })), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('clarification never browses')) as browse:
            result = module._execute_market_summary_chat(
                self._chat_data(axis='', message='عدّل القسم'), tenant_id=self.tenant)
        browse.assert_not_called()
        self.assertTrue(result['success'], result)
        self.assertTrue(result.get('clarification'))
        self.assertEqual(result['reply'], 'هل تقصد العرض أم الطلب؟')
        self.assertIsNone(result['proposal'])
        self.assertFalse(result.get('searchPerformed'))

    def test_full_project_facts_reach_the_turn_prompt(self):
        module = self.application_module
        captured = {}

        def fake_chat(system, prompt, **kwargs):
            captured['prompt'] = prompt
            return _chat_result({'reply': 'رد', 'ops': []})

        project_data = {
            'project_name': 'برج الاختبار',
            'custom_boardroom_note': 'قاعة احتفالات مائية معلّقة',
        }
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', side_effect=fake_chat):
            result = module._execute_market_summary_chat(
                self._chat_data(axis='', projectData=project_data),
                tenant_id=self.tenant)
        self.assertTrue(result['success'], result)
        self.assertIn('قاعة احتفالات مائية معلّقة', captured['prompt'])

    def test_research_off_forbids_phase_b(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'أحتاج بحثًا أولًا', 'needs_research': True,
                    'queries': ['إيجارات حي النرجس'], 'ops': []})), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('research=off forbids browsing')) as browse:
            result = module._execute_market_summary_chat(
                self._chat_data(research='off'), tenant_id=self.tenant)
        browse.assert_not_called()
        self.assertTrue(result['success'], result)
        self.assertTrue(result['reply'])
        self.assertFalse(result.get('searchPerformed'))

    def test_research_turn_browses_and_runs_the_source_pipeline(self):
        module = self.application_module
        research_url = 'https://sakani.sa/reports-and-data/rent-index'
        browse_kwargs = []

        def fake_browse(system, prompt, usage_ctx=None, **kwargs):
            browse_kwargs.append(kwargs)
            return _chat_result({
                'reply': 'وجدت أرقامًا جديدة',
                'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'العرض بالمصدر الجديد'}],
                'sources_add': [
                    {'name': 'مؤشر الإيجار', 'url': research_url, 'data_date': '2025-06'}],
            }, citations=[research_url])

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'سأبحث', 'needs_research': True,
                    'queries': ['إيجار المتر حي النرجس'], 'ops': []})) as chat_mock, \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_verify_market_urls', return_value=set()) as verify_mock, \
                patch.object(market_study, 'apply_search_citations',
                             wraps=market_study.apply_search_citations) as citations_spy, \
                patch.object(market_study, 'flag_out_of_period_sources',
                             wraps=market_study.flag_out_of_period_sources) as period_spy:
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=self.tenant)

        self.assertTrue(result['success'], result)
        self.assertEqual(chat_mock.call_count, 1)
        self.assertEqual(len(browse_kwargs), 1)
        # Phase B uses the same local interactive browser and pinned SearXNG
        # provider as the main market summary.
        self.assertIs(browse_kwargs[0].get('local_tools'), True)
        self.assertEqual(browse_kwargs[0].get('search_provider'), 'searxng')
        self.assertEqual(browse_kwargs[0].get('search_budget'), 3)
        self.assertNotIn('server_tools', browse_kwargs[0])
        self.assertNotIn('tool_choice', browse_kwargs[0])
        self.assertEqual(browse_kwargs[0].get('max_steps'), 8)
        self.assertEqual(browse_kwargs[0].get('max_tokens'), 66000)
        self.assertTrue(result.get('searchPerformed'))
        self.assertIn(research_url, result.get('citations') or [])
        self.assertTrue(citations_spy.called)
        verify_mock.assert_called()
        self.assertTrue(period_spy.called)
        proposal = result['proposal']
        self.assertIsNotNone(proposal)
        self.assertTrue(any(
            op.get('op') == 'set_axis' and op.get('key') == 'supply'
            for op in proposal.get('ops') or []))
        self.assertTrue(any(
            research_url in str(row.get('url') or '')
            for row in proposal.get('sourcesAdd') or []))

    def test_history_is_capped_to_the_last_12_messages(self):
        module = self.application_module
        history = [
            {'role': 'user' if index % 2 == 0 else 'assistant',
             'content': f'm{index:02d}'}
            for index in range(20)
        ]
        captured = {}

        def fake_chat(system, prompt, **kwargs):
            captured['prompt'] = prompt
            return _chat_result({'reply': 'r', 'ops': []})

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', side_effect=fake_chat):
            module._execute_market_summary_chat(
                self._chat_data(history=history), tenant_id=self.tenant)
        prompt = captured['prompt']
        self.assertIn('m19', prompt)
        self.assertIn('m08', prompt)
        self.assertNotIn('m07', prompt)
        self.assertNotIn('m00', prompt)

    def test_empty_message_is_refused(self):
        module = self.application_module
        result = 'unset'
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat',
                             side_effect=AssertionError('must not call')) as chat_mock:
            try:
                result = module._execute_market_summary_chat(
                    self._chat_data(message='   '), tenant_id=self.tenant)
            except AssertionError:
                raise
            except Exception:
                result = None
        self.assertFalse(chat_mock.called)
        if result is not None:
            self.assertFalse(result.get('success'), result)

    def test_invalid_axis_is_refused(self):
        module = self.application_module
        result = 'unset'
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat',
                             side_effect=AssertionError('must not call')) as chat_mock:
            try:
                result = module._execute_market_summary_chat(
                    self._chat_data(axis='not_an_axis'), tenant_id=self.tenant)
            except AssertionError:
                raise
            except Exception:
                result = None
        self.assertFalse(chat_mock.called)
        if result is not None:
            self.assertFalse(result.get('success'), result)

    def test_consolidate_regenerates_only_flagged_dependents(self):
        module = self.application_module
        captured = {}
        model_out = {
            'one_block_summary': 'فقرة تنفيذية مولدة من جديد',
            'decision': market_study.DECISION_OPTIONS[1],
            'swot': {'strengths': 'قوة مولدة', 'weaknesses': 'ضعف',
                     'opportunities': 'فرصة', 'threats': 'تهديد'},
        }

        def fake_chat(system, prompt, **kwargs):
            captured['prompt'] = prompt
            captured['kwargs'] = kwargs
            return _chat_result(model_out)

        data = {
            'summary': {'supply': 'النص النهائي للعرض'},
            'sources': [{'name': 'سكني', 'url': 'https://sakani.sa/x', 'data_date': '2025'}],
            'swot': {'strengths': 'قديمة'},
            'decision': market_study.DECISION_OPTIONS[0],
            'one_block_summary': 'الفقرة القديمة',
            'stale': {'swot': True},
            'city': 'جدة',
            'projectType': 'سكني',
        }
        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', side_effect=fake_chat), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('consolidate never browses')) as browse:
            result = module._execute_market_summary_consolidate(data, tenant_id=self.tenant)

        browse.assert_not_called()
        self.assertTrue(result['success'], result)
        self.assertEqual(result.get('swot'), model_out['swot'])
        self.assertNotIn('decision', result)
        self.assertNotIn('one_block_summary', result)
        max_tokens = captured['kwargs'].get('max_tokens')
        self.assertTrue(max_tokens and int(max_tokens) <= 8000, max_tokens)

    # -- routes and job dispatch ----------------------------------------------

    def test_chat_route_discuss_turn_round_trip(self):
        module = self.application_module
        with patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result(
                    {'reply': 'رد', 'ops': []})):
            response = self.client.post(
                '/api/market-study/summary/chat',
                headers=self.headers, json=self._chat_data())
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['reply'], 'رد')
        self.assertIsNone(body.get('proposal'))

    def test_approved_summary_locks_op_turns_but_not_discussion(self):
        module = self.application_module
        with self.app.app_context():
            db.update_draft_section_status_by_id(
                self.tenant, self.draft_id, {'section-market-study': 'approved'})
        with patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result({
                    'reply': 'اقتراح تعديل',
                    'ops': [{'op': 'set_axis', 'key': 'supply', 'value': 'v'}],
                })):
            response = self.client.post(
                '/api/market-study/summary/chat',
                headers=self.headers, json=self._chat_data())
        self.assertEqual(response.status_code, 409, response.get_json())
        body = response.get_json()
        self.assertFalse(body['success'])
        self.assertEqual(body.get('error_code'), 'SUMMARY_APPROVAL_LOCKED')

        with patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result(
                {'reply': 'نقاش بلا تعديل', 'ops': []})):
            response = self.client.post(
                '/api/market-study/summary/chat',
                headers=self.headers, json=self._chat_data())
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['reply'], 'نقاش بلا تعديل')
        self.assertIsNone(body.get('proposal'))

    def test_worker_dispatches_the_new_job_kinds(self):
        module = self.application_module
        seen = {}

        def chat_exec(data, tenant_id=None, progress=None):
            seen['chat'] = (data, tenant_id)
            return {'success': True, 'reply': 'تم', 'proposal': None,
                    'searchPerformed': False, 'citations': []}

        def consolidate_exec(data, tenant_id=None, progress=None):
            seen['consolidate'] = (data, tenant_id)
            return {'success': True, 'swot': {'strengths': 'مولدة'}}

        with self.app.app_context(), \
                patch.object(module, '_execute_market_summary_chat', side_effect=chat_exec), \
                patch.object(module, '_execute_market_summary_consolidate',
                             side_effect=consolidate_exec):
            module._market_job_worker(
                self.app, self.tenant, 'summary_chat',
                {'axis': 'supply', 'message': 'x'}, 'jobchat0001')
            module._market_job_worker(
                self.app, self.tenant, 'summary_consolidate',
                {'stale': {'swot': True}}, 'jobcons0001')
            chat_job = module._read_market_job(self.tenant, 'jobchat0001')
            cons_job = module._read_market_job(self.tenant, 'jobcons0001')

        self.assertEqual(seen['chat'][1], self.tenant)
        self.assertEqual(seen['consolidate'][1], self.tenant)
        self.assertEqual(chat_job.get('kind'), 'summary_chat')
        self.assertEqual(chat_job.get('status'), 'completed')
        self.assertEqual(chat_job.get('reply'), 'تم')
        self.assertEqual(cons_job.get('kind'), 'summary_consolidate')
        self.assertEqual(cons_job.get('status'), 'completed')

    def test_market_summary_job_resume_route_reuses_saved_checkpoint(self):
        module = self.application_module
        job_id = 'jobresume01'
        resume_state = {'researchers': {'task-1': {'parsed': {'findings': []}}},
                        'evidencePages': []}
        module._write_market_job(self.tenant, job_id, {
            'status': 'failed', 'success': False, 'kind': 'summary',
            'failureReason': 'insufficient_credit',
            'payload': {'kind': 'summary', 'data': self._chat_data()},
            'actor': {'user_id': None, 'user_name': 'مدير',
                      'user_role': 'company_admin'},
            'resumeState': resume_state,
        })

        public = self.client.get(
            f'/api/market-study/jobs/{job_id}', headers=self.headers)
        self.assertEqual(public.status_code, 200)
        self.assertTrue(public.get_json()['canResume'])
        self.assertNotIn('resumeState', public.get_json())

        with patch.object(module.threading, 'Thread', _InlineThread), \
                patch.object(module, '_market_job_worker') as worker:
            response = self.client.post(
                f'/api/market-study/jobs/{job_id}/resume', headers=self.headers)
        self.assertEqual(response.status_code, 202, response.get_json())
        self.assertEqual(response.get_json()['jobId'], job_id)
        self.assertEqual(worker.call_args.args[2], 'summary')
        self.assertEqual(worker.call_args.args[3], self._chat_data())
        self.assertEqual(worker.call_args.args[4], job_id)
        stored = module._read_market_job(self.tenant, job_id)
        self.assertEqual(stored.get('status'), 'queued')
        self.assertEqual(stored.get('resumeState'), resume_state)

    def test_market_summary_resume_route_rejects_non_credit_failures(self):
        module = self.application_module
        job_id = 'jobnoretry01'
        module._write_market_job(self.tenant, job_id, {
            'status': 'failed', 'success': False, 'kind': 'summary',
            'failureReason': 'search_not_run',
            'payload': {'kind': 'summary', 'data': self._chat_data()},
            'actor': {},
        })
        response = self.client.post(
            f'/api/market-study/jobs/{job_id}/resume', headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['failureReason'], 'job_not_resumable')

    def test_summary_worker_persists_research_checkpoint_for_later_resume(self):
        module = self.application_module
        job_id = 'jobcheckpoint01'
        initial_state = {'researchers': {}, 'evidencePages': []}
        saved_state = {'researchers': {'task-1': {'parsed': {'findings': []}}},
                       'evidencePages': []}
        module._write_market_job(self.tenant, job_id, {
            'status': 'queued', 'success': True, 'kind': 'summary',
            'payload': {'kind': 'summary', 'data': self._chat_data()},
            'actor': {}, 'resumeState': initial_state,
        })

        def stop_for_credit(_data, tenant_id=None, progress=None,
                            resume_state=None, checkpoint=None):
            self.assertEqual(tenant_id, self.tenant)
            self.assertEqual(resume_state, initial_state)
            checkpoint(saved_state)
            return {'success': False, 'failureReason': 'insufficient_credit',
                    'error': 'رصيد غير كافٍ'}

        with self.app.app_context(), \
                patch.object(module, '_execute_market_summary', side_effect=stop_for_credit):
            module._market_job_worker(
                self.app, self.tenant, 'summary', self._chat_data(), job_id)

        job = module._read_market_job(self.tenant, job_id)
        self.assertEqual(job.get('status'), 'failed')
        self.assertEqual(job.get('resumeState'), saved_state)
        self.assertTrue(module._public_job(job)['canResume'])

    def test_redispatch_accepts_new_kinds_and_still_refuses_unknown(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.object(module.threading, 'Thread', _InlineThread), \
                patch.object(module, '_market_job_worker') as worker:
            for kind in ('summary_chat', 'summary_consolidate'):
                ok = module._redispatch_job(
                    '.market_jobs', self.tenant, f'job{kind}01',
                    {'kind': kind, 'payload': {'data': {}}, 'actor': {}})
                self.assertTrue(ok, kind)
            refused = module._redispatch_job(
                '.market_jobs', self.tenant, 'jobbogus01',
                {'kind': 'bogus_kind', 'payload': {'data': {}}, 'actor': {}})
        self.assertFalse(refused)
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(
            [call.args[2] for call in worker.call_args_list],
            ['summary_chat', 'summary_consolidate'])

    def test_consolidate_route_round_trip(self):
        module = self.application_module
        model_out = {'swot': {'strengths': 'مولدة'}}
        with patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', return_value=_chat_result(model_out)):
            response = self.client.post(
                '/api/market-study/summary/consolidate',
                headers=self.headers,
                json={'draftId': self.draft_id,
                      'summary': {'supply': 'نص'},
                      'swot': {}, 'decision': '', 'one_block_summary': '',
                      'sources': [], 'stale': {'swot': True},
                      'city': 'جدة'})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual((body.get('swot') or {}).get('strengths'), 'مولدة')


if __name__ == '__main__':
    unittest.main()
