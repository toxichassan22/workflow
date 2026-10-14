"""Browse-agent pool/deadline/session contract tests — search-rework board A2.

The market job's shared pieces ride into ``run_browse_agent`` as three new
optional params (docs/plans/مشكله البحث/plan.md — A2):

- ``evidence_pool`` — an A1 ``EvidencePool``. Before executing
  ``web_search(q)`` the agent asks ``pool.query_results(q)``; a stored list
  answers the tool call without touching the browser (a pool hit). After real
  executions the run feeds ``add_query`` / ``add_page`` / ``mark_failed``.
- ``deadline`` — a unix timestamp checked before each model round and each
  tool execution; on expiry the loop stops and returns
  ``{'error': {'message': 'deadline_exceeded'}, 'usage':…, 'browse_trace':…}``
  with whatever was already collected.
- ``session`` — a caller-owned browser session used for all tool execution and
  NEVER closed by the agent (the agent only closes sessions it opened itself).

``browser.py`` side of the same task: ``_DEFAULT_ORDER`` drops the dead DDG
provider (it returns 418 anomaly pages — documented in ``browser.py``) while
``BROWSER_SEARCH_PROVIDER=ddg`` stays a valid pin, and
``thread_local_browser()`` / ``close_thread_browser()`` give the verify pools
one live ``BrowserWorker`` per thread via ``_tls.worker``.

Zero network and zero Chromium — the transport, the sessions and the clock
are all faked. Run like every other suite, one suite per process::

    python -m unittest tests.market.test_browse_agent_pool
"""

import contextlib
import json
import os
import sys
import time
import types
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
    import evidence as _evidence_module
    EvidencePool = getattr(_evidence_module, 'EvidencePool', None)
except Exception:  # A1 has not landed yet — stub pools drive the contract
    EvidencePool = None

_FINAL_TEXT = '{"exists": true, "official_url": "https://roafed.sa/x", "price": null}'
_PAGE_URL = 'https://sa.aqar.fm/projects/roafed-yasmeen'
_PAGE_TITLE = 'مشروع روافد الياسمين'
_PAGE_TEXT = 'صفحة المشروع الرسمية تحتوي تفاصيل الأسعار والمساحات ' * 300


def _usage(prompt=10, completion=5):
    return {'prompt_tokens': prompt, 'completion_tokens': completion,
            'total_tokens': prompt + completion}


def _tool_call(name, args, index=0):
    return {'id': f'call_{index}', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}


def _fn_response(calls, prompt=10, completion=5):
    if isinstance(calls, tuple):
        calls = [calls]
    return {'choices': [{'message': {
        'role': 'assistant', 'content': None,
        'tool_calls': [_tool_call(name, args, index)
                       for index, (name, args) in enumerate(calls)]},
        'finish_reason': 'tool_calls'}],
        'usage': _usage(prompt, completion)}


def _text_response(text=_FINAL_TEXT, prompt=10, completion=5):
    return {'choices': [{'message': {'role': 'assistant', 'content': text},
                         'finish_reason': 'stop'}],
            'usage': _usage(prompt, completion)}


def _ok_page(url, title=_PAGE_TITLE, text=_PAGE_TEXT):
    return {'url': url, 'final_url': url, 'title': title,
            'text': text, 'error': None}


def _default_results(_query):
    return [{'title': _PAGE_TITLE, 'url': _PAGE_URL, 'snippet': 'نتيجة أولى'},
            {'title': 'wasalt', 'url': 'https://wasalt.sa/x', 'snippet': 'نتيجة ثانية'}]


class _FakeWorker:
    """Session stand-in — the same shape the agent's ``_tool_callable``
    expects: ``web_search``/``open_url`` methods plus lifecycle flags."""

    def __init__(self, open_url=None, web_search=None):
        self._open_url = open_url
        self._web_search = web_search
        self.searches = []
        self.opened = []
        self.closed = False
        self.started = False
        self.exited = False
        self.is_open = True

    def open_url(self, url, timeout=20, **_kw):
        self.opened.append(url)
        if self._open_url is not None:
            return self._open_url(url)
        return _ok_page(url)

    def web_search(self, query, max_results=8, **_kw):
        self.searches.append(query)
        if self._web_search is not None:
            return self._web_search(query)
        return _default_results(query)

    def start(self):
        self.started = True
        self.is_open = True
        return self

    def close(self):
        self.closed = True
        self.is_open = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.exited = True
        self.closed = True
        self.is_open = False
        return False


def _scripted_chat(responses, calls):
    def fake(messages, **kwargs):
        calls.append({'messages': [dict(m) for m in (messages or [])],
                      'kwargs': kwargs})
        if len(calls) < len(responses):
            return responses[len(calls) - 1]
        return responses[-1]
    return fake


class _RecordingPool:
    """EvidencePool-API stub recording every call the agent makes — the
    contract is the API surface, so a stub drives it while A1 lands."""

    def __init__(self, queries=None):
        self._queries = dict(queries or {})
        self._pages = {}
        self._failed = {}
        self.calls = []
        self._hits = 0

    @staticmethod
    def _fold(query):
        return ' '.join(str(query or '').split()).casefold()

    def add_query(self, query, results):
        self.calls.append(('add_query', query))
        key = self._fold(query)
        if key in self._queries:
            return 0
        self._queries[key] = list(results or [])
        return len(self._queries[key])

    def query_results(self, query):
        self.calls.append(('query_results', query))
        found = self._queries.get(self._fold(query))
        if found is not None:
            self._hits += 1
        return found

    def add_page(self, url, title='', content='', final_url='', via='browser'):
        key = str(final_url or url or '')
        self.calls.append(('add_page', key))
        page = self._pages.setdefault(
            key, {'url': key, 'title': '', 'content': ''})
        if title and not page.get('title'):
            page['title'] = title
        if content:
            page['content'] = (page.get('content') or '') + '\n' + str(content)
            page['content'] = page['content'].strip()
        return page

    def mark_failed(self, url, reason):
        self.calls.append(('mark_failed', str(url)))
        self._failed[str(url)] = reason

    def get_page(self, url):
        self.calls.append(('get_page', str(url)))
        return self._pages.get(str(url))

    def page_failed(self, url):
        return self._failed.get(str(url))

    def pages(self):
        return list(self._pages.values())

    def stats(self):
        return {'queries': len(self._queries), 'pages': len(self._pages),
                'pool_hits': self._hits}


def _make_pool(**kw):
    return EvidencePool() if EvidencePool is not None else _RecordingPool(**kw)


@contextlib.contextmanager
def _patched_transport(chat_impl, worker=None):
    """Fake the model transport and the self-opened session — the run under
    test can then only reach the fakes or the caller-provided session."""
    worker = worker or _FakeWorker()
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(agent, 'openrouter_chat', chat_impl))
    for mod, name in ((browser, 'browser_session'), (agent, 'browser_session')):
        stack.enter_context(mock.patch.object(
            mod, name, lambda *a, **kw: worker, create=True))
    for mod, name in ((browser, 'BrowserWorker'), (agent, 'BrowserWorker')):
        stack.enter_context(mock.patch.object(
            mod, name, lambda *a, **kw: worker, create=True))
    with stack:
        yield worker


class EvidencePoolHitTests(unittest.TestCase):
    def test_pool_hit_answers_web_search_without_the_browser(self):
        cached = [{'title': 'مخزنة', 'url': 'https://cached.sa/p',
                   'snippet': 'نتيجة مخزنة'}]
        pool = _RecordingPool(queries={'مشروع روافد الياسمين': cached})
        worker = _FakeWorker()
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'مشروع روافد الياسمين'})),
            _text_response(),
        ], calls)
        with _patched_transport(chat, worker):
            result = agent.run_browse_agent(
                'تحقق', max_steps=4, evidence_pool=pool)
        self.assertNotIn('error', result)
        # The stored list answered the call — Chromium never searched.
        self.assertEqual(worker.searches, [])
        self.assertIn(('query_results', 'مشروع روافد الياسمين'), pool.calls)
        # The cached results were fed back to the model as the tool answer.
        transcript = json.dumps(calls[-1]['messages'], ensure_ascii=False)
        self.assertIn('https://cached.sa/p', transcript)
        # And the hit is not re-stored as a fresh query result.
        self.assertNotIn(('add_query', 'مشروع روافد الياسمين'), pool.calls)

    @unittest.skipIf(EvidencePool is None, 'A1 evidence pool not landed yet')
    def test_pool_hit_is_counted_on_the_real_pool(self):
        pool = EvidencePool()
        pool.add_query('استعلام', [{'title': 't', 'url': 'https://a.sa/',
                                    'snippet': 's'}])
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'استعلام'})),
            _text_response(),
        ], calls)
        with _patched_transport(chat):
            agent.run_browse_agent('task', max_steps=4, evidence_pool=pool)
        self.assertGreaterEqual(pool.stats().get('pool_hits', 0), 1)


class EvidencePoolFeedTests(unittest.TestCase):
    def test_real_search_and_open_feed_the_pool(self):
        pool = _RecordingPool()
        worker = _FakeWorker()
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'منافس'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        with _patched_transport(chat, worker):
            result = agent.run_browse_agent(
                'تحقق', max_steps=5, evidence_pool=pool)
        self.assertNotIn('error', result)
        self.assertEqual(worker.searches, ['منافس'])
        self.assertIn(('add_query', 'منافس'), pool.calls)
        self.assertIsNotNone(pool.query_results('منافس'))
        self.assertIn(('add_page', _PAGE_URL), pool.calls)
        self.assertIsNotNone(pool.get_page(_PAGE_URL))

    def test_failed_open_marks_the_pool_failure(self):
        pool = _RecordingPool()
        worker = _FakeWorker(open_url=lambda url: {
            'url': url, 'final_url': url, 'title': '', 'text': '',
            'error': 'timeout'})
        calls = []
        chat = _scripted_chat([
            _fn_response(('open_url', {'url': 'https://dead.sa/x'})),
            _text_response(),
        ], calls)
        with _patched_transport(chat, worker):
            agent.run_browse_agent('تحقق', max_steps=4, evidence_pool=pool)
        self.assertIn(('mark_failed', 'https://dead.sa/x'), pool.calls)

    def test_run_without_a_pool_behaves_as_before(self):
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)
        with _patched_transport(chat):
            result = agent.run_browse_agent('task', max_steps=4)
        self.assertNotIn('error', result)
        self.assertEqual(result['choices'][0]['message']['content'], _FINAL_TEXT)


class ProgressEventTests(unittest.TestCase):
    """``on_event`` turns a multi-minute browse run into a live progress feed —
    without it the job bar only moved between stages and looked dead."""

    def test_on_event_fires_round_tool_tool_done_and_done(self):
        worker = _FakeWorker()
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'منافس تجريبي'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        events = []
        with _patched_transport(chat, worker):
            result = agent.run_browse_agent('task', max_steps=6,
                                            on_event=events.append)
        self.assertNotIn('error', result)
        phases = [event.get('phase') for event in events]
        self.assertEqual(phases[0], 'round')
        self.assertIn('tool', phases)
        self.assertIn('tool_done', phases)
        self.assertEqual(phases[-1], 'done')
        tool_events = [event for event in events if event.get('phase') == 'tool']
        self.assertEqual([event['tool'] for event in tool_events],
                         ['web_search', 'open_url'])
        self.assertEqual(tool_events[0]['hint'], 'منافس تجريبي')
        self.assertEqual(tool_events[1]['hint'], _PAGE_URL)
        done = events[-1]
        self.assertTrue(done.get('ok'))
        self.assertGreaterEqual(done.get('searches') or 0, 1)

    def test_on_event_failure_does_not_kill_the_run(self):
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _text_response(),
        ], calls)

        def boom(_event):
            raise RuntimeError('ui died')

        with _patched_transport(chat):
            result = agent.run_browse_agent('task', max_steps=4, on_event=boom)
        self.assertNotIn('error', result)
        self.assertEqual(result['choices'][0]['message']['content'], _FINAL_TEXT)

    def test_tool_done_marks_a_failed_open(self):
        worker = _FakeWorker(open_url=lambda url: {
            'url': url, 'final_url': url, 'title': '', 'text': '',
            'error': 'timeout'})
        calls = []
        chat = _scripted_chat([
            _fn_response(('open_url', {'url': 'https://dead.sa/x'})),
            _text_response(),
        ], calls)
        events = []
        with _patched_transport(chat, worker):
            agent.run_browse_agent('task', max_steps=4, on_event=events.append)
        tool_dones = [e for e in events if e.get('phase') == 'tool_done']
        self.assertEqual(len(tool_dones), 1)
        self.assertFalse(tool_dones[0]['ok'])

    def test_log_line_flushes_so_tail_sees_steps_live(self):
        """gunicorn block-buffers worker stdout — without flush=True a
        [BROWSE AGENT] line waits for ~8KB of output, so tail -f shows
        nothing while the run is alive."""
        printed = []
        with mock.patch('builtins.print') as mocked:
            agent._log_line('step line')
        self.assertTrue(mocked.called)
        self.assertEqual(mocked.call_args.kwargs.get('flush'), True)


class DeadlineTests(unittest.TestCase):
    def test_expired_deadline_stops_before_the_first_round(self):
        calls = []
        chat = _scripted_chat([_text_response()], calls)
        with _patched_transport(chat):
            result = agent.run_browse_agent(
                'task', max_steps=4, deadline=time.time() - 1)
        self.assertEqual((result.get('error') or {}).get('message'),
                         'deadline_exceeded')
        self.assertIn('usage', result)
        self.assertIn('browse_trace', result)
        self.assertEqual(calls, [])

    def test_deadline_mid_run_returns_with_collected_pages(self):
        worker = _FakeWorker()
        calls = []
        now = [time.time()]
        deadline = now[0] + 60

        def open_then_expire(url):
            page = _ok_page(url)
            now[0] += 9999
            return page

        worker._open_url = open_then_expire
        chat = _scripted_chat([
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        clock = mock.patch('time.time', lambda: now[0])
        # Cover `from time import time` import styles in the agent module too:
        # patching agent.time with an object whose .time attr is the clock
        # works whether the impl holds the module or the function.
        fake_time = types.SimpleNamespace(time=lambda: now[0])
        with _patched_transport(chat, worker), clock, \
                mock.patch.object(agent, 'time', fake_time, create=True):
            result = agent.run_browse_agent(
                'task', max_steps=5, deadline=deadline, session=worker)
        self.assertEqual((result.get('error') or {}).get('message'),
                         'deadline_exceeded')
        trace_urls = [e.get('url') for e in result.get('browse_trace') or []]
        self.assertIn(_PAGE_URL, trace_urls)


class SessionTests(unittest.TestCase):
    def test_caller_session_runs_tools_and_is_never_closed(self):
        worker = _FakeWorker()
        calls = []
        chat = _scripted_chat([
            _fn_response(('web_search', {'query': 'q'})),
            _fn_response(('open_url', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        forbidden = mock.patch.object(
            agent, '_browser_session',
            side_effect=AssertionError('agent opened its own session'))
        with _patched_transport(chat), forbidden:
            result = agent.run_browse_agent(
                'task', max_steps=5, session=worker)
        self.assertNotIn('error', result)
        self.assertEqual(worker.searches, ['q'])
        self.assertEqual(worker.opened, [_PAGE_URL])
        self.assertFalse(worker.closed)
        self.assertFalse(worker.exited)
        self.assertFalse(worker.started)


class ProviderOrderTests(unittest.TestCase):
    def test_ddg_is_out_of_the_default_rotation(self):
        self.assertEqual(browser._DEFAULT_ORDER, ['brave', 'yahoo', 'bing'])
        self.assertNotIn('ddg', browser._DEFAULT_ORDER)

    def test_providers_default_to_the_new_order(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('BROWSER_SEARCH_PROVIDER', None)
            self.assertEqual(browser._providers(), ['brave', 'yahoo', 'bing'])

    def test_ddg_stays_a_pinnable_provider(self):
        with mock.patch.dict(os.environ, {'BROWSER_SEARCH_PROVIDER': 'ddg'}):
            providers = browser._providers()
        self.assertEqual(providers[0], 'ddg')
        self.assertIn('brave', providers)
        self.assertIn('yahoo', providers)
        self.assertIn('bing', providers)


class ThreadLocalBrowserTests(unittest.TestCase):
    def test_thread_local_browser_reuses_the_threads_worker(self):
        made = []

        class _TWorker(_FakeWorker):
            def __init__(self, *a, **kw):
                super().__init__()
                self.is_open = False
                made.append(self)

            def start(self):
                self.is_open = True
                self.started = True
                return self

        with mock.patch.object(browser, 'BrowserWorker', _TWorker):
            first = browser.thread_local_browser()
            second = browser.thread_local_browser()
        self.assertIs(first, second)
        self.assertIs(getattr(browser._tls, 'worker', None), first)
        self.assertTrue(first.is_open)

    def test_close_thread_browser_closes_and_unbinds(self):
        class _TWorker(_FakeWorker):
            def __init__(self, *a, **kw):
                super().__init__()
                self.is_open = True

        with mock.patch.object(browser, 'BrowserWorker', _TWorker):
            worker = browser.thread_local_browser()
            browser.close_thread_browser()
            self.assertTrue(worker.closed)
            self.assertIsNone(getattr(browser._tls, 'worker', None))


if __name__ == '__main__':
    unittest.main()
