"""Browse-agent loop contract tests.

``modules/web_browse/agent.py`` runs one OpenRouter chat-completions loop per
research task — the task's own model decides when to call ``web_search`` /
``open_url``, the module executes those calls locally against the headless
Chromium session (``browser.py``), feeds each result back as a ``tool``
message, and repackages the outcome as an OpenRouter-shaped response plus
``browse_trace`` and ``url_citation`` annotations.

These tests never touch the network or a real browser: the transport
(``agent.openrouter_chat`` — the indirection over the app's
``call_openrouter_messages``) and the browser surface (``browser_session`` /
``BrowserWorker`` / module-level ``open_url``/``web_search``) are all faked.
The contract fixes signatures but not import style, so each dependency name is
patched on the consumer module *and* the source module — ``from x import f``
and ``import x; x.f()`` are intercepted identically.

Run like every other suite::

    python -m unittest tests.web_browse.test_agent_loop
"""

import contextlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent  # noqa: E402  modules/web_browse/agent.py
import browser  # noqa: E402  modules/web_browse/browser.py

try:
    import evidence  # noqa: E402  modules/web_browse/evidence.py — the A1 pool
except Exception:
    evidence = None

_FINAL_TEXT = '{"exists": true, "official_url": "https://sa.aqar.fm/x", "price": null}'
_PAGE_URL = 'https://sa.aqar.fm/projects/alajlan-riviera-16'
_PAGE_TITLE = 'مشروع العجلان ريفيرا 16'
_PAGE_TEXT = 'صفحة المشروع الرسمية تحتوي تفاصيل الأسعار والمساحات ' * 400


def _usage(prompt=10, completion=5):
    return {'prompt_tokens': prompt,
            'completion_tokens': completion,
            'total_tokens': prompt + completion}


def _tool_call(name, args, index=0):
    return {
        'id': f'call_{index}',
        'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)},
    }


def _fn_response(calls, prompt=10, completion=5):
    """One assistant turn carrying tool calls — OpenAI messages shape."""
    if isinstance(calls, tuple):
        calls = [calls]
    return {
        'choices': [{
            'message': {
                'role': 'assistant',
                'content': None,
                'tool_calls': [_tool_call(name, args, index)
                               for index, (name, args) in enumerate(calls)],
            },
            'finish_reason': 'tool_calls',
        }],
        'usage': _usage(prompt, completion),
    }


def _text_response(text=_FINAL_TEXT, prompt=10, completion=5):
    return {
        'choices': [{
            'message': {'role': 'assistant', 'content': text},
            'finish_reason': 'stop',
        }],
        'usage': _usage(prompt, completion),
    }


def _ok_page(url):
    return {
        'url': url,
        'final_url': url,
        'title': _PAGE_TITLE,
        'text': _PAGE_TEXT,
        'error': None,
    }


def _default_results(_query):
    return [
        {'title': _PAGE_TITLE, 'url': _PAGE_URL, 'snippet': 'نتيجة أولى'},
        {'title': 'wasalt', 'url': 'https://wasalt.sa/x', 'snippet': 'نتيجة ثانية'},
    ]


class _FakeWorker:
    """One object covering every lifecycle the contract allows: usable as a
    plain worker, as ``with browser_session() as w`` and as ``BrowserWorker()``
    — it exposes the browser operations either way."""

    def __init__(self, open_url=None, web_search=None):
        self._open_url = open_url
        self._web_search = web_search
        self.closed = False

    def open_url(self, url, timeout=20, **_kw):
        if self._open_url is not None:
            return self._open_url(url)
        return _ok_page(url)

    def web_search(self, query, max_results=8, **_kw):
        if self._web_search is not None:
            return self._web_search(query)
        return _default_results(query)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


def _citation_payload(annotation):
    """Tolerate both ``{"url_citation": {...}}`` and the OpenRouter wrapper
    ``{"type": "url_citation", "url_citation": {...}}``."""
    if not isinstance(annotation, dict):
        return {}
    return annotation.get('url_citation') or annotation


class _FakePool:
    """EvidencePool-contract fake (modules/web_browse/evidence.py lands with
    A1): folded-query dedupe, page store keyed by final_url, failure records
    and a pool_hits counter — enough to prove the agent consults and feeds it.
    """

    def __init__(self):
        self.queries = {}
        self.pages = {}
        self.failed = {}
        self.hits = 0

    @staticmethod
    def _fold(text):
        return ' '.join(str(text or '').split()).casefold()

    def add_query(self, query, results):
        key = self._fold(query)
        if key in self.queries:
            return 0
        self.queries[key] = list(results or [])
        return len(self.queries[key])

    def query_results(self, query):
        key = self._fold(query)
        if key not in self.queries:
            return None
        self.hits += 1
        return self.queries[key]

    def add_page(self, url, title='', content='', final_url='', via='browser'):
        key = str(final_url or url or '').strip()
        if not key:
            return
        self.pages[key] = {'url': key, 'final_url': key,
                           'title': title, 'content': content}

    def mark_failed(self, url, reason):
        self.failed[str(url)] = reason

    def get_page(self, url):
        url = str(url or '').strip()
        for key, page in self.pages.items():
            if key == url or page.get('url') == url:
                return page
        return None

    def page_failed(self, url):
        return self.failed.get(str(url))

    def pages(self):
        return [dict(page) for page in self.pages.values()]

    def stats(self):
        return {'queries': len(self.queries),
                'pages': len(self.pages), 'pool_hits': self.hits}


@contextlib.contextmanager
def _patched_pipeline(chat_impl, worker=None, open_url=None, web_search=None):
    """Intercept every documented dependency on both the consumer (``agent``)
    and the source modules so either import style is covered."""
    worker = worker or _FakeWorker(open_url=open_url, web_search=web_search)
    session_factory = lambda *a, **kw: worker  # noqa: E731
    open_fn = open_url or (lambda url, **_kw: _ok_page(url))
    search_fn = web_search or _default_results
    stack = contextlib.ExitStack()
    for mod, name, new in (
        (agent, 'openrouter_chat', chat_impl),
        (browser, 'browser_session', session_factory),
        (agent, 'browser_session', session_factory),
        (browser, 'BrowserWorker', lambda *a, **kw: worker),
        (agent, 'BrowserWorker', lambda *a, **kw: worker),
        (browser, 'open_url', open_fn),
        (agent, 'open_url', open_fn),
        (browser, 'web_search', search_fn),
        (agent, 'web_search', search_fn),
    ):
        stack.enter_context(mock.patch.object(mod, name, new, create=True))
    with stack:
        yield worker


def _scripted_chat(responses, calls):
    def fake(messages, **kwargs):
        calls.append({'messages': [dict(m) for m in (messages or [])],
                      'kwargs': kwargs})
        if len(calls) < len(responses):
            return responses[len(calls) - 1]
        return responses[-1]

    return fake


class RunBrowseAgentLoopTests(unittest.TestCase):
    def test_search_open_then_final_text_builds_citation(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'مشروع العجلان ريفيرا 16'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(prompt=30, completion=12),
        ], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('تحقق من المنافس', max_steps=5)

        self.assertNotIn('error', result)
        message = result['choices'][0]['message']
        self.assertEqual(message['content'], _FINAL_TEXT)

        annotations = [_citation_payload(a) for a in message.get('annotations') or []]
        citations = [a for a in annotations if a.get('url')]
        self.assertEqual([c['url'] for c in citations], [_PAGE_URL])
        self.assertEqual(citations[0]['title'], _PAGE_TITLE)
        self.assertTrue(citations[0].get('content'))
        self.assertLessEqual(len(citations[0]['content']), 8000)

        trace_urls = [e.get('url') for e in result.get('browse_trace') or []]
        self.assertIn(_PAGE_URL, trace_urls)

        usage = result.get('usage') or {}
        self.assertEqual(usage.get('prompt_tokens'), 10 + 10 + 30)
        self.assertEqual(usage.get('completion_tokens'), 5 + 5 + 12)

    def test_tool_results_are_fed_back_as_tool_messages(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl):
            agent.run_browse_agent('task', max_steps=4)

        self.assertGreaterEqual(len(calls), 2)
        second_round = calls[1]['messages']
        roles = [m.get('role') for m in second_round]
        self.assertEqual(roles[:2], ['system', 'user'])
        # The assistant turn keeps its raw tool_calls and each answer rides as
        # a tool-role message keyed by the call id.
        assistant = second_round[2]
        self.assertEqual(assistant.get('role'), 'assistant')
        self.assertTrue(assistant.get('tool_calls'))
        tool_msg = second_round[3]
        self.assertEqual(tool_msg.get('role'), 'tool')
        self.assertEqual(tool_msg.get('tool_call_id'), 'call_0')
        self.assertIn('نتيجة', tool_msg.get('content') or '')

    def test_parallel_tool_calls_each_get_a_result_message(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response([
                ('open_url', {'url': _PAGE_URL}),
                ('open_url', {'url': 'https://wasalt.sa/x'}),
            ]),
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        tool_msgs = [m for m in calls[1]['messages'] if m.get('role') == 'tool']
        self.assertEqual([m.get('tool_call_id') for m in tool_msgs],
                         ['call_0', 'call_1'])
        self.assertEqual(
            len(result['choices'][0]['message'].get('annotations') or []), 2)

    def test_failed_open_is_traced_but_not_cited(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': 'https://wasalt.sa/property/deep'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)

        def flaky_open(url):
            if 'wasalt' in url:
                return {'url': url, 'final_url': url, 'title': '', 'text': '',
                        'error': 'timeout'}
            return _ok_page(url)

        with _patched_pipeline(chat_impl, worker=_FakeWorker(open_url=flaky_open)):
            result = agent.run_browse_agent('task', max_steps=6)

        self.assertNotIn('error', result)
        message = result['choices'][0]['message']
        annotations = [_citation_payload(a) for a in message.get('annotations') or []]
        self.assertEqual([a.get('url') for a in annotations], [_PAGE_URL])
        trace_urls = [e.get('url') for e in result.get('browse_trace') or []]
        self.assertIn('https://wasalt.sa/property/deep', trace_urls)
        self.assertIn(_PAGE_URL, trace_urls)

    def test_step_cap_returns_error_shape(self):
        calls = []
        chat_impl = _scripted_chat(
            [_fn_response(('web_search', {'query': 'q'}))], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=3)

        self.assertIn('error', result)
        self.assertLessEqual(len(calls), 3)
        self.assertIsInstance(result.get('browse_trace') or [], list)

    def test_transport_error_never_raises(self):
        chat_impl = lambda *_a, **_kw: {'error': {'message': 'boom'}}  # noqa: E731

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertIn('error', result)
        self.assertEqual(result['error'].get('message'), 'boom')

    def test_fatal_refusal_dict_survives_for_downstream_detection(self):
        """A wallet/key refusal must reach the caller with its error_code —
        _ai_fatal_error_dict reads it straight off the result."""
        fatal = {'error': {'fatal': True, 'message': 'استُنفد الرصيد',
                           'error_code': 'INSUFFICIENT_CREDITS',
                           'http_status': 402}}
        chat_impl = lambda *_a, **_kw: dict(fatal)  # noqa: E731

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertEqual(result['error'].get('error_code'), 'INSUFFICIENT_CREDITS')
        self.assertTrue(result['error'].get('fatal'))

    def test_search_budget_param_caps_searches(self):
        calls = []
        chat_impl = _scripted_chat(
            [_fn_response(('web_search', {'query': 'q'}))], calls)
        searches = []

        def counting_search(query):
            searches.append(query)
            return _default_results(query)

        with _patched_pipeline(chat_impl, web_search=counting_search):
            result = agent.run_browse_agent('task', max_steps=6, search_budget=2)

        # The hard cap granted exactly two real searches; every later call
        # comes back as a budget refusal the model can act on instead of
        # burning the step cap.
        self.assertEqual(len(searches), 2)
        transcript = json.dumps(calls[-1]['messages'], ensure_ascii=False, default=str)
        self.assertIn('search_budget_exceeded', transcript)
        self.assertIn('error', result)

    def test_preamble_advertises_one_less_than_the_hard_cap(self):
        calls = []
        chat_impl = _scripted_chat([_text_response()], calls)

        with _patched_pipeline(chat_impl):
            agent.run_browse_agent('task')
        self.assertEqual(calls[0]['messages'][0].get('role'), 'system')
        self.assertIn('عمليتي بحث', calls[0]['messages'][0].get('content') or '')

        calls.clear()
        with _patched_pipeline(chat_impl):
            agent.run_browse_agent('task', search_budget=8)
        self.assertIn('7 عمليات بحث', calls[0]['messages'][0].get('content') or '')

    def test_output_cap_and_reasoning_effort_reach_the_transport(self):
        seen = []

        def fake(messages, **kw):
            seen.append(kw)
            return _text_response()

        with _patched_pipeline(fake):
            agent.run_browse_agent('task', max_tokens=12345,
                                   reasoning_effort='max')
        self.assertEqual(seen[0].get('max_tokens'), 12345)
        self.assertEqual(seen[0].get('reasoning_effort'), 'max')

        seen.clear()
        with _patched_pipeline(fake):
            agent.run_browse_agent('task')
        self.assertEqual(seen[0].get('max_tokens'), 4000)
        self.assertIsNone(seen[0].get('reasoning_effort'))

    def test_task_model_is_forwarded_on_every_round(self):
        """The loop belongs to the caller's model — the same model that would
        have answered the task without tools drives every round."""
        seen = []

        def fake(messages, **kw):
            seen.append(kw)
            if len(seen) == 1:
                return _fn_response(('web_search', {'query': 'q'}))
            return _text_response()

        with _patched_pipeline(fake):
            agent.run_browse_agent('task', model='anthropic/claude-haiku-5.5')

        self.assertEqual(
            [kw.get('model') for kw in seen],
            ['anthropic/claude-haiku-5.5'] * len(seen))
        # And every round declares the same local tools — the two readers plus
        # the interaction surface (inspect/click/type/scroll).
        names = {tool['function']['name'] for kw in seen
                 for tool in kw.get('tools') or []}
        self.assertEqual(names, {'web_search', 'open_url', 'inspect_page',
                                 'click_element', 'type_text', 'scroll_page'})

    def test_reasoning_effort_refusal_retries_without_it(self):
        """A provider that rejects the effort knob gets the same model again,
        minus the knob — never a different transport or a silent failure."""
        seen = []

        def fake(messages, **kw):
            seen.append(dict(kw))
            if kw.get('reasoning_effort'):
                return {'error': {'message': 'reasoning_effort: Invalid value'}}
            return _text_response()

        with _patched_pipeline(fake):
            result = agent.run_browse_agent('task', reasoning_effort='max')

        self.assertNotIn('error', result)
        self.assertEqual(seen[0].get('reasoning_effort'), 'max')
        self.assertNotIn('reasoning_effort', seen[1])

    def test_never_cites_pages_the_agent_did_not_open(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        message = result['choices'][0]['message']
        annotations = [_citation_payload(a) for a in message.get('annotations') or []]
        self.assertEqual([a for a in annotations if a.get('url')], [])

    def test_usage_ctx_reaches_every_round(self):
        seen = []

        def fake(messages, **kw):
            seen.append(kw)
            return _text_response()

        with _patched_pipeline(fake):
            agent.run_browse_agent(
                'task', usage_ctx={'tenant_id': 't-9', 'flow': 'market'})
        self.assertEqual(seen[0].get('usage_ctx'),
                         {'tenant_id': 't-9', 'flow': 'market'})


class RunBrowseAgentPoolTests(unittest.TestCase):
    """evidence_pool / deadline / session — the shared-evidence contract the
    market job board (docs/plans/مشكله البحث/plan.md) hangs on this loop."""

    def test_pooled_query_answers_search_without_touching_the_browser(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'مشروع العجلان ريفيرا 16'})),
            _text_response(),
        ], calls)
        searches = []

        def counting_search(query):
            searches.append(query)
            return _default_results(query)

        pool = _FakePool()
        pool.add_query('مشروع العجلان ريفيرا 16', _default_results(''))

        with _patched_pipeline(chat_impl, web_search=counting_search):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(searches, [])
        self.assertEqual(pool.hits, 1)
        # The cached results still reach the model as a tool message.
        transcript = json.dumps(calls[-1]['messages'],
                                ensure_ascii=False, default=str)
        self.assertIn('نتيجة', transcript)

    def test_real_executions_feed_the_pool_and_dedupe_repeats(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            # Same query again — must be served from the pool, not the SERP.
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)
        searches = []

        def counting_search(query):
            searches.append(query)
            return _default_results(query)

        pool = _FakePool()
        with _patched_pipeline(chat_impl, web_search=counting_search):
            result = agent.run_browse_agent(
                'task', max_steps=6, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(searches, ['q'])
        self.assertEqual(pool.hits, 1)
        self.assertEqual(pool.queries.get('q'), _default_results('q'))
        pooled = pool.get_page(_PAGE_URL)
        self.assertIsNotNone(pooled)
        self.assertEqual(pooled['title'], _PAGE_TITLE)
        self.assertTrue(pooled['content'])

    def test_pooled_page_answers_open_url_without_a_fetch(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        opens = []

        def counting_open(url):
            opens.append(url)
            return _ok_page(url)

        pool = _FakePool()
        pool.add_page(_PAGE_URL, title='cached title', content='cached body')

        with _patched_pipeline(chat_impl, open_url=counting_open):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(opens, [])
        # The pooled page still lands in the run's own citations.
        message = result['choices'][0]['message']
        annotations = [_citation_payload(a)
                       for a in message.get('annotations') or []]
        self.assertEqual([a.get('url') for a in annotations], [_PAGE_URL])
        trace = [e for e in result['browse_trace'] if e.get('pool')]
        self.assertEqual(len(trace), 1)

    def test_pool_failure_record_short_circuits_reopen(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': 'https://wasalt.sa/x'})),
            _text_response(),
        ], calls)
        opens = []

        def counting_open(url):
            opens.append(url)
            return _ok_page(url)

        pool = _FakePool()
        pool.mark_failed('https://wasalt.sa/x', 'timeout')

        with _patched_pipeline(chat_impl, open_url=counting_open):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(opens, [])
        transcript = json.dumps(calls[-1]['messages'],
                                ensure_ascii=False, default=str)
        self.assertIn('timeout', transcript)

    def test_failed_fetch_is_marked_in_the_pool(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': 'https://wasalt.sa/x'})),
            _text_response(),
        ], calls)

        def flaky_open(url):
            return {'url': url, 'final_url': url, 'title': '', 'text': '',
                    'error': 'http_404'}

        pool = _FakePool()
        with _patched_pipeline(chat_impl, open_url=flaky_open):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(pool.page_failed('https://wasalt.sa/x'), 'http_404')
        self.assertIsNone(pool.get_page('https://wasalt.sa/x'))

    def test_deadline_before_first_round_returns_deadline_exceeded(self):
        calls = []
        chat_impl = _scripted_chat([_text_response()], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', deadline=0)

        self.assertEqual(result['error'].get('message'), 'deadline_exceeded')
        self.assertIn('usage', result)
        self.assertIn('browse_trace', result)
        self.assertEqual(calls, [])

    def test_deadline_mid_run_keeps_collected_pages(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        ticks = iter([10, 10, 10, 200])
        clock = mock.Mock()
        clock.time = lambda: next(ticks, 10 ** 9)

        with _patched_pipeline(chat_impl), \
                mock.patch.object(agent, 'time', clock):
            result = agent.run_browse_agent('task', max_steps=6, deadline=100)

        self.assertEqual(result['error'].get('message'), 'deadline_exceeded')
        # The second model round never ran — the check precedes the transport.
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.get('browse_trace'))
        urls = [a.get('url_citation', {}).get('url')
                for a in result.get('annotations') or []]
        self.assertIn(_PAGE_URL, urls)

    def test_deadline_stops_between_tool_calls(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response([
                ('open_url', {'url': _PAGE_URL}),
                ('open_url', {'url': 'https://wasalt.sa/x'}),
            ]),
            _text_response(),
        ], calls)
        opens = []

        def counting_open(url):
            opens.append(url)
            return _ok_page(url)

        ticks = iter([10, 10, 10, 200])
        clock = mock.Mock()
        clock.time = lambda: next(ticks, 10 ** 9)

        with _patched_pipeline(chat_impl, open_url=counting_open), \
                mock.patch.object(agent, 'time', clock):
            result = agent.run_browse_agent('task', max_steps=6, deadline=100)

        self.assertEqual(result['error'].get('message'), 'deadline_exceeded')
        self.assertEqual(opens, [_PAGE_URL])

    def test_caller_session_is_used_and_never_closed(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        worker = _FakeWorker()

        with mock.patch.object(agent, 'openrouter_chat', chat_impl), \
                mock.patch.object(agent, '_browser_session') as session_factory:
            result = agent.run_browse_agent(
                'task', max_steps=4, session=worker)

        self.assertNotIn('error', result)
        session_factory.assert_not_called()
        self.assertFalse(worker.closed)
        message = result['choices'][0]['message']
        annotations = [_citation_payload(a)
                       for a in message.get('annotations') or []]
        self.assertEqual([a.get('url') for a in annotations], [_PAGE_URL])

    def test_self_opened_session_is_still_closed(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        worker = _FakeWorker()

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        self.assertTrue(worker.closed)

    @unittest.skipUnless(
        getattr(evidence, 'EvidencePool', None) is not None,
        'modules/web_browse/evidence.py has not landed')
    def test_real_evidence_pool_round_trip(self):
        """Against the real EvidencePool: one real search, the repeat served
        from the pool, the opened page stored and re-served — no browser
        traffic beyond the first pass."""
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _fn_response(('web_search', {'query': 'q'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        searches, opens = [], []

        def counting_search(query):
            searches.append(query)
            return _default_results(query)

        def counting_open(url):
            opens.append(url)
            return _ok_page(url)

        pool = evidence.EvidencePool()
        with _patched_pipeline(chat_impl, web_search=counting_search,
                               open_url=counting_open):
            result = agent.run_browse_agent(
                'task', max_steps=8, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(searches, ['q'])
        self.assertEqual(opens, [_PAGE_URL])
        stats = pool.stats()
        self.assertEqual(stats.get('queries'), 1)
        self.assertEqual(stats.get('pages'), 1)
        # pool_hits counts served query results; the second open_url landing
        # in the pool is proven by opens holding a single real fetch.
        self.assertGreaterEqual(stats.get('pool_hits'), 1)


if __name__ == '__main__':
    unittest.main()
