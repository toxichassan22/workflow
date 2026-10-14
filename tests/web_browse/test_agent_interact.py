"""Browse-agent interaction-tools contract tests.

``modules/web_browse/agent.py`` declares, alongside ``web_search``/``open_url``,
the interactive surface — ``inspect_page`` (numbered elements + text),
``click_element``, ``type_text`` and ``scroll_page`` — so the task model can
use a page (fill a search box, apply a filter, scroll a listing) instead of
only reading it. These tests fake the transport and the worker exactly like
``test_agent_loop.py``; no network, no real Chromium.

Run like every other suite::

    python -m unittest tests.web_browse.test_agent_interact
"""

import contextlib
import json
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

_PAGE_URL = 'https://aqar.fm/search/riyadh'
_PAGE_TITLE = 'عقار — نتائج البحث'
_PAGE_TEXT = 'نتائج الفلترة على مدينة الرياض — أسعار ومساحات ' * 200
_ELEMENTS = [
    {'i': 0, 'tag': 'input', 'type': 'search', 'text': '',
     'href': '', 'placeholder': 'ابحث عن مدينة'},
    {'i': 1, 'tag': 'button', 'type': 'submit', 'text': 'تطبيق الفلاتر',
     'href': '', 'placeholder': ''},
    {'i': 2, 'tag': 'a', 'type': '', 'text': 'مشروع روافد الياسمين',
     'href': 'https://aqar.fm/p/1', 'placeholder': ''},
]


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


def _text_response(text='{"done": true}', prompt=10, completion=5):
    return {
        'choices': [{
            'message': {'role': 'assistant', 'content': text},
            'finish_reason': 'stop',
        }],
        'usage': _usage(prompt, completion),
    }


def _state(url):
    return {'url': url, 'final_url': url, 'title': _PAGE_TITLE,
            'text': _PAGE_TEXT,
            'elements': [dict(e) for e in _ELEMENTS],
            'error': None}


def _ok_page(url):
    return {'url': url, 'final_url': url, 'title': _PAGE_TITLE,
            'text': _PAGE_TEXT, 'error': None}


class _FakeWorker:
    """Session fake: the two read tools plus the four interaction tools, with
    an ``actions`` log proving what the agent dispatched and a ``raise_on``
    set for failure-path tests."""

    def __init__(self):
        self.actions = []
        self.raise_on = set()
        self.closed = False

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise RuntimeError(f'{name} blew up')

    def open_url(self, url, timeout=20, **_kw):
        self._maybe_raise('open_url')
        return _ok_page(url)

    def web_search(self, query, max_results=8, **_kw):
        return [{'title': _PAGE_TITLE, 'url': _PAGE_URL, 'snippet': 'نتيجة'}]

    def inspect_page(self, url=None, **_kw):
        self._maybe_raise('inspect_page')
        self.actions.append(('inspect_page', url))
        return _state(url or 'https://aqar.fm/current')

    def click_element(self, index):
        self._maybe_raise('click_element')
        self.actions.append(('click_element', index))
        return _state('https://aqar.fm/filtered')

    def type_text(self, index, text, submit=False, **_kw):
        self._maybe_raise('type_text')
        self.actions.append(('type_text', index, text, submit))
        return _state('https://aqar.fm/results')

    def scroll_page(self, direction='down', **_kw):
        self._maybe_raise('scroll_page')
        self.actions.append(('scroll_page', direction))
        return _state('https://aqar.fm/current')

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class _FakePool:
    def __init__(self):
        self.pages = {}
        self.failed = {}
        self.queries = {}

    def add_query(self, query, results):
        self.queries[str(query)] = list(results or [])

    def query_results(self, query):
        return self.queries.get(str(query))

    def add_page(self, url, title='', content='', final_url='', via='browser'):
        key = str(final_url or url or '').strip()
        if key:
            self.pages[key] = {'url': key, 'title': title, 'content': content}

    def mark_failed(self, url, reason):
        self.failed[str(url)] = reason

    def get_page(self, url):
        return self.pages.get(str(url))

    def page_failed(self, url):
        return self.failed.get(str(url))


@contextlib.contextmanager
def _patched_pipeline(chat_impl, worker=None):
    worker = worker or _FakeWorker()
    session_factory = lambda *a, **kw: worker  # noqa: E731
    stack = contextlib.ExitStack()
    for mod, name, new in (
        (agent, 'openrouter_chat', chat_impl),
        (browser, 'browser_session', session_factory),
        (agent, 'browser_session', session_factory),
        (browser, 'BrowserWorker', lambda *a, **kw: worker),
        (agent, 'BrowserWorker', lambda *a, **kw: worker),
        (browser, 'open_url', lambda url, **_kw: _ok_page(url)),
        (browser, 'web_search', lambda q, **_kw: []),
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


def _citation_urls(result):
    message = result['choices'][0]['message']
    out = []
    for annotation in message.get('annotations') or []:
        payload = (annotation.get('url_citation')
                   if isinstance(annotation, dict) else None) or annotation
        if isinstance(payload, dict) and payload.get('url'):
            out.append(payload['url'])
    return out


def _tool_payloads(calls):
    payloads = []
    for call in calls:
        for message in call['messages']:
            if message.get('role') != 'tool':
                continue
            try:
                payloads.append(json.loads(message.get('content') or '{}'))
            except (TypeError, ValueError):
                pass
    return payloads


class InteractionToolDeclarationTests(unittest.TestCase):
    def test_interaction_tools_are_declared_every_round(self):
        seen = []

        def fake(messages, **kw):
            seen.append(kw)
            return _text_response()

        with _patched_pipeline(fake):
            agent.run_browse_agent('task')

        names = {tool['function']['name'] for kw in seen
                 for tool in kw.get('tools') or []}
        self.assertEqual(
            names, {'web_search', 'open_url', 'inspect_page',
                    'click_element', 'type_text', 'scroll_page'})

    def test_preamble_keeps_the_search_cap_and_names_the_tools(self):
        calls = []
        chat_impl = _scripted_chat([_text_response()], calls)

        with _patched_pipeline(chat_impl):
            agent.run_browse_agent('task')

        system = calls[0]['messages'][0].get('content') or ''
        self.assertIn('عمليتي بحث', system)
        self.assertIn('open_url', system)
        self.assertIn('click_element', system)


class InteractionDispatchTests(unittest.TestCase):
    def test_inspect_page_opens_url_and_returns_numbered_elements(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('inspect_page', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl) as worker:
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        self.assertIn(('inspect_page', _PAGE_URL), worker.actions)
        payloads = _tool_payloads(calls)
        self.assertTrue(payloads)
        elements = payloads[-1].get('elements') or []
        self.assertEqual(elements[1].get('text'), 'تطبيق الفلاتر')
        self.assertEqual(elements[0].get('tag'), 'input')
        # An inspected page was genuinely read — it lands as a citation.
        self.assertIn(_PAGE_URL, _citation_urls(result))

    def test_click_type_scroll_dispatch_to_the_worker(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response([
                ('click_element', {'index': 1}),
                ('type_text', {'index': 0, 'text': 'الرياض', 'submit': True}),
                ('scroll_page', {'direction': 'down'}),
            ]),
            _text_response(),
        ], calls)
        worker = _FakeWorker()

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        self.assertEqual(worker.actions[:3], [
            ('click_element', 1),
            ('type_text', 0, 'الرياض', True),
            ('scroll_page', 'down'),
        ])
        # Every action's refreshed state is a genuinely-read page.
        self.assertIn('https://aqar.fm/filtered', _citation_urls(result))
        self.assertIn('https://aqar.fm/results', _citation_urls(result))

    def test_type_text_submit_defaults_to_false(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('type_text', {'index': 0, 'text': 'جدة'})),
            _text_response(),
        ], calls)
        worker = _FakeWorker()

        with _patched_pipeline(chat_impl, worker=worker):
            agent.run_browse_agent('task', max_steps=4)

        self.assertIn(('type_text', 0, 'جدة', False), worker.actions)

    def test_invalid_action_arguments_return_error_not_exception(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('click_element', {'index': 'abc'})),
            _text_response(),
        ], calls)

        with _patched_pipeline(chat_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        payloads = _tool_payloads(calls)
        self.assertEqual(payloads[-1].get('error'), 'invalid_arguments')

    def test_action_exception_is_data_not_a_crash(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('click_element', {'index': 9})),
            _text_response(),
        ], calls)
        worker = _FakeWorker()
        worker.raise_on.add('click_element')

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        payloads = _tool_payloads(calls)
        self.assertTrue(payloads[-1].get('error'))

    def test_missing_interaction_method_reports_unavailable(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('scroll_page', {'direction': 'down'})),
            _text_response(),
        ], calls)
        worker = _FakeWorker()
        worker.scroll_page = None  # older worker without the interactive surface

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertNotIn('error', result)
        payloads = _tool_payloads(calls)
        self.assertTrue(payloads[-1].get('error'))


class InteractionPoolTests(unittest.TestCase):
    def test_inspect_bypasses_needs_interaction_failures(self):
        """needs_interaction is the exact mark this tool answers — it must
        not be short-circuited by the pool the way open_url is."""
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('inspect_page', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        pool = _FakePool()
        pool.mark_failed(_PAGE_URL, 'needs_interaction')
        worker = _FakeWorker()

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertIn(('inspect_page', _PAGE_URL), worker.actions)

    def test_inspect_bypasses_thin_content_failures(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('inspect_page', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        pool = _FakePool()
        pool.mark_failed(_PAGE_URL, 'thin_content')

        with _patched_pipeline(chat_impl) as worker:
            agent.run_browse_agent('task', max_steps=4, evidence_pool=pool)

        self.assertIn(('inspect_page', _PAGE_URL), worker.actions)

    def test_inspect_respects_hard_pool_failures(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('inspect_page', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        pool = _FakePool()
        pool.mark_failed(_PAGE_URL, 'http_404')
        worker = _FakeWorker()

        with _patched_pipeline(chat_impl, worker=worker):
            result = agent.run_browse_agent(
                'task', max_steps=4, evidence_pool=pool)

        self.assertNotIn('error', result)
        self.assertEqual(worker.actions, [])
        payloads = _tool_payloads(calls)
        self.assertEqual(payloads[-1].get('error'), 'http_404')

    def test_inspected_page_is_stored_in_the_pool(self):
        calls = []
        chat_impl = _scripted_chat([
            _fn_response(('inspect_page', {'url': _PAGE_URL})),
            _text_response(),
        ], calls)
        pool = _FakePool()

        with _patched_pipeline(chat_impl):
            agent.run_browse_agent('task', max_steps=4, evidence_pool=pool)

        stored = pool.get_page(_PAGE_URL)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.get('title'), _PAGE_TITLE)


if __name__ == '__main__':
    unittest.main()
