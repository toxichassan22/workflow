"""Browse-agent loop contract tests (task A6).

``modules/web_browse/agent.py`` runs a Vertex ``generateContent`` loop with two
function declarations — ``web_search`` and ``open_url`` — executed through the
A1 browser session, then repackages the outcome as an OpenRouter-shaped chat
response plus ``browse_trace`` and ``url_citation`` annotations.

These tests never touch the network or a real browser: the transport
(``vertex_generate``) and the browser surface (``browser_session`` /
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
import vertex_client  # noqa: E402  modules/web_browse/vertex_client.py

_FINAL_TEXT = '{"exists": true, "official_url": "https://sa.aqar.fm/x", "price": null}'
_PAGE_URL = 'https://sa.aqar.fm/projects/alajlan-riviera-16'
_PAGE_TITLE = 'مشروع العجلان ريفيرا 16'
_PAGE_TEXT = 'صفحة المشروع الرسمية تحتوي تفاصيل الأسعار والمساحات ' * 400


def _usage(prompt=10, completion=5):
    return {
        'promptTokenCount': prompt,
        'candidatesTokenCount': completion,
        'totalTokenCount': prompt + completion,
    }


def _fn_response(name, args, prompt=10, completion=5):
    return {
        'candidates': [{
            'content': {
                'role': 'model',
                'parts': [{'functionCall': {'name': name, 'args': args}}],
            },
            'finishReason': 'STOP',
        }],
        'usageMetadata': _usage(prompt, completion),
    }


def _text_response(text=_FINAL_TEXT, prompt=10, completion=5):
    return {
        'candidates': [{
            'content': {'role': 'model', 'parts': [{'text': text}]},
            'finishReason': 'STOP',
        }],
        'usageMetadata': _usage(prompt, completion),
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
    — it exposes the A1 operations either way."""

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


@contextlib.contextmanager
def _patched_pipeline(vertex_impl, worker=None, open_url=None, web_search=None):
    """Intercept every documented dependency on both the consumer (``agent``)
    and the source modules so either import style is covered."""
    worker = worker or _FakeWorker(open_url=open_url, web_search=web_search)
    session_factory = lambda *a, **kw: worker  # noqa: E731
    open_fn = open_url or (lambda url, **_kw: _ok_page(url))
    search_fn = web_search or _default_results
    stack = contextlib.ExitStack()
    for mod, name, new in (
        (vertex_client, 'vertex_generate', vertex_impl),
        (agent, 'vertex_generate', vertex_impl),
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


def _scripted_vertex(responses, calls):
    def fake(*_a, **_kw):
        calls.append(_a[0] if _a else _kw.get('contents'))
        if len(calls) < len(responses):
            return responses[len(calls) - 1]
        return responses[-1]

    return fake


class RunBrowseAgentLoopTests(unittest.TestCase):
    def test_search_open_then_final_text_builds_citation(self):
        calls = []
        vertex_impl = _scripted_vertex([
            _fn_response('web_search', {'query': 'مشروع العجلان ريفيرا 16'}),
            _fn_response('open_url', {'url': _PAGE_URL}),
            _text_response(prompt=30, completion=12),
        ], calls)

        with _patched_pipeline(vertex_impl):
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

    def test_tool_results_are_fed_back_to_the_model(self):
        calls = []
        vertex_impl = _scripted_vertex([
            _fn_response('web_search', {'query': 'q'}),
            _text_response(),
        ], calls)

        with _patched_pipeline(vertex_impl):
            agent.run_browse_agent('task', max_steps=4)

        self.assertGreaterEqual(len(calls), 2)
        second_round = json.dumps(calls[1], ensure_ascii=False, default=str)
        self.assertIn('functionResponse', second_round)
        self.assertIn('نتيجة', second_round)

    def test_failed_open_is_traced_but_not_cited(self):
        calls = []
        vertex_impl = _scripted_vertex([
            _fn_response('open_url', {'url': 'https://wasalt.sa/property/deep'}),
            _fn_response('open_url', {'url': _PAGE_URL}),
            _text_response(),
        ], calls)

        def flaky_open(url):
            if 'wasalt' in url:
                return {'url': url, 'final_url': url, 'title': '', 'text': '',
                        'error': 'timeout'}
            return _ok_page(url)

        with _patched_pipeline(vertex_impl, worker=_FakeWorker(open_url=flaky_open)):
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
        vertex_impl = _scripted_vertex(
            [_fn_response('web_search', {'query': 'q'})], calls)

        with _patched_pipeline(vertex_impl):
            result = agent.run_browse_agent('task', max_steps=3)

        self.assertIn('error', result)
        self.assertLessEqual(len(calls), 3)
        self.assertIsInstance(result.get('browse_trace') or [], list)

    def test_transport_error_never_raises(self):
        vertex_impl = lambda *a, **kw: {'error': {'message': 'boom'}}  # noqa: E731

        with _patched_pipeline(vertex_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        self.assertIn('error', result)
        self.assertEqual(result['error'].get('message'), 'boom')

    def test_never_cites_pages_the_agent_did_not_open(self):
        calls = []
        vertex_impl = _scripted_vertex([
            _fn_response('web_search', {'query': 'q'}),
            _text_response(),
        ], calls)

        with _patched_pipeline(vertex_impl):
            result = agent.run_browse_agent('task', max_steps=4)

        message = result['choices'][0]['message']
        annotations = [_citation_payload(a) for a in message.get('annotations') or []]
        self.assertEqual([a for a in annotations if a.get('url')], [])


if __name__ == '__main__':
    unittest.main()
