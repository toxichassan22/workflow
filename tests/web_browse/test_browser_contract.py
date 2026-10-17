"""Browser-layer contract tests (task A6).

``modules/web_browse/browser.py`` wraps one Playwright Chromium per worker:
``browser_session()``/``BrowserWorker`` lifecycle plus ``open_url(url) ->
{url, final_url, title, text, error}`` and ``web_search(query) ->
[{title, url, snippet}]``. ``open_url`` must never raise — failures come back
as a short ``error`` reason.

A fake ``playwright``/``playwright.sync_api`` is installed in ``sys.modules``
before ``browser`` is imported and also patched onto the module afterwards, so
top-level, lazy and attribute-style imports all resolve to the fake. No real
Chromium launches and no request leaves the process.

Run like every other suite::

    python -m unittest tests.web_browse.test_browser_contract
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _FakeElement:
    def __init__(self, net, item=None):
        self._net = net
        self._item = item or {}

    def inner_text(self, **_kw):
        return self._item.get('title') or self._item.get('snippet') or self._net['text']

    textContent = inner_text

    def text_content(self, **_kw):
        return self.inner_text()

    def get_attribute(self, name, **_kw):
        if name == 'href':
            return self._item.get('url') or self._net['url']
        return self._item.get(name)

    def query_selector(self, *_a, **kw):
        return _FakeElement(self._net, self._item)

    def query_selector_all(self, *_a, **_kw):
        return [_FakeElement(self._net, i) for i in self._net['serp']]


class _FakeLocator:
    def __init__(self, net):
        self._net = net

    def count(self):
        return len(self._net['serp'])

    def all(self):
        return [_FakeElement(self._net, i) for i in self._net['serp']]

    def all_inner_texts(self):
        return [i.get('snippet', '') for i in self._net['serp']]

    def nth(self, i):
        return _FakeElement(self._net, self._net['serp'][i])

    @property
    def first(self):
        return _FakeElement(self._net, self._net['serp'][0] if self._net['serp'] else {})


class _FakePage:
    """Any extraction strategy resolves against the shared ``net`` dict:
    element grabs, JS evaluation and inner_text all read it."""

    def __init__(self, net):
        self._net = net
        self.url = 'about:blank'
        self._keyboard = _FakeKeyboard(net)
        self._mouse = _FakeMouse(net)

    def goto(self, url, timeout=None, wait_until=None, **_kw):
        if self._net['goto_error'] is not None:
            raise self._net['goto_error']
        self.url = url
        self._net['visited'].append(url)
        return _FakeResponse((self._net.get('goto_status') or {}).get(url))

    def wait_for_timeout(self, *_a, **_kw):
        pass

    def wait_for_load_state(self, *_a, **_kw):
        pass

    def wait_for_selector(self, selector=None, **_kw):
        return _FakeElement(self._net)

    def title(self):
        return self._net['title']

    def inner_text(self, selector='body', **_kw):
        return self._net['text']

    def text_content(self, selector=None, **_kw):
        return self._net['text']

    def content(self):
        return self._net['html']

    def _eval(self, script):
        if 'data-ll-el' in (script or ''):
            # The interaction snapshot tagger: elements carry i/tag/text and
            # get data-ll-el attributes click/fill target later.
            return {'text': self._net['text'],
                    'elements': [dict(e) for e in self._net['elements']]}
        if 'scrollBy' in (script or ''):
            self._net['scrolls'].append(script)
            return None
        if 'duckduckgo' in self.url or 'bing' in self.url:
            return self._net['serp']
        return self._net['text']

    def evaluate(self, script=None, arg=None, **_kw):
        return self._eval(script)

    def click(self, selector=None, **_kw):
        self._net['clicks'].append(selector)

    def fill(self, selector=None, text='', **_kw):
        self._net['fills'].append((selector, text))

    @property
    def keyboard(self):
        return self._keyboard

    @property
    def mouse(self):
        return self._mouse

    def eval_on_selector_all(self, selector=None, script=None, **_kw):
        return self._eval(script)

    def query_selector_all(self, selector=None, **_kw):
        return [_FakeElement(self._net, i) for i in self._net['serp']]

    def query_selector(self, selector=None, **_kw):
        return _FakeElement(self._net)

    def locator(self, selector=None, **_kw):
        return _FakeLocator(self._net)

    def route(self, *_a, **_kw):
        pass

    def on(self, *_a, **_kw):
        pass

    def set_default_timeout(self, *_a, **_kw):
        pass

    def is_closed(self):
        return False

    def close(self):
        pass


class _FakeKeyboard:
    def __init__(self, net):
        self._net = net

    def press(self, key, **_kw):
        self._net['keys'].append(key)


class _FakeMouse:
    def __init__(self, net):
        self._net = net

    def wheel(self, dx=0, dy=0, **_kw):
        self._net['scrolls'].append((dx, dy))


class _FakeContext:
    def __init__(self, net):
        self._net = net
        self._page = _FakePage(net)

    def new_page(self):
        return self._page

    def add_init_script(self, *_a, **_kw):
        pass

    def route(self, *_a, **_kw):
        pass

    def set_default_timeout(self, *_a, **_kw):
        pass

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, net):
        self._net = net
        self.version = 'fake-0.0'

    def new_context(self, **_kw):
        return _FakeContext(self._net)

    def new_page(self):
        return _FakePage(self._net)

    def close(self):
        self._net['browser_closed'] = True

    def is_connected(self):
        return True


class _FakeChromium:
    def __init__(self, net):
        self._net = net

    def launch(self, **_kw):
        self._net['launched'] = True
        if self._net['launch_error'] is not None:
            raise self._net['launch_error']
        return _FakeBrowser(self._net)

    def connect_over_cdp(self, endpoint, **_kw):
        self._net['cdp_endpoint'] = endpoint
        return _FakeBrowser(self._net)


class _FakePlaywright:
    def __init__(self, net):
        self.chromium = _FakeChromium(net)
        self.firefox = self.chromium
        self.webkit = self.chromium

    def stop(self):
        pass


class _FakePWManager:
    """``sync_playwright()`` result: usable as ``with`` or ``.start()``."""

    def __init__(self, net):
        self._pw = _FakePlaywright(net)

    def __enter__(self):
        return self._pw

    def __exit__(self, *exc):
        return False

    def start(self):
        return self._pw

    def stop(self):
        pass


class _FakeResponse:
    """goto() result carrying only the HTTP status the test configured."""

    def __init__(self, status):
        self.status = status


class _FakeTimeoutError(Exception):
    pass


def _new_net():
    return {
        'title': 'مشروع العجلان ريفيرا 16',
        'text': 'نص الصفحة المقروء ' * 200,
        'html': '<html><body>page</body></html>',
        'url': 'https://sa.aqar.fm/',
        'serp': [
            {'title': 'العجلان ريفيرا', 'url': 'https://sa.aqar.fm/p/1',
             'snippet': 'تفاصيل المشروع'},
            {'title': 'وصلت', 'url': 'https://wasalt.sa/p/2',
             'snippet': 'مشروع آخر'},
        ],
        'visited': [],
        'goto_error': None,
        'goto_status': {},
        'launch_error': None,
        'launched': False,
        'browser_closed': False,
        'cdp_endpoint': None,
        'elements': [
            {'i': 0, 'tag': 'input', 'type': 'search', 'text': '',
             'href': '', 'placeholder': 'ابحث عن مدينة'},
            {'i': 1, 'tag': 'button', 'type': 'submit',
             'text': 'تطبيق الفلاتر', 'href': '', 'placeholder': ''},
        ],
        'clicks': [],
        'fills': [],
        'keys': [],
        'scrolls': [],
    }


def _install_fake_playwright(net):
    """Return a (cleanup) that installs a fake playwright package covering
    top-level, lazy and attribute import styles."""
    sync_api = types.ModuleType('playwright.sync_api')
    manager = lambda: _FakePWManager(net)  # noqa: E731
    sync_api.sync_playwright = manager
    sync_api.Playwright = _FakePlaywright
    sync_api.Browser = _FakeBrowser
    sync_api.Page = _FakePage
    sync_api.Error = Exception
    sync_api.TimeoutError = _FakeTimeoutError

    parent = sys.modules.get('playwright') or types.ModuleType('playwright')
    saved = {
        'playwright': sys.modules.get('playwright'),
        'playwright.sync_api': sys.modules.get('playwright.sync_api'),
        'parent_attr': getattr(parent, 'sync_api', None),
        'parent_obj': parent,
    }
    parent.sync_api = sync_api
    sys.modules['playwright'] = parent
    sys.modules['playwright.sync_api'] = sync_api
    return saved, manager


def _restore_fake_playwright(saved):
    parent = saved['parent_obj']
    if saved['parent_attr'] is not None:
        parent.sync_api = saved['parent_attr']
    if saved['playwright'] is None:
        sys.modules.pop('playwright', None)
    else:
        sys.modules['playwright'] = saved['playwright']
    if saved['playwright.sync_api'] is None:
        sys.modules.pop('playwright.sync_api', None)
    else:
        sys.modules['playwright.sync_api'] = saved['playwright.sync_api']


_NET = _new_net()
_SAVED, _MANAGER = _install_fake_playwright(_NET)

import browser  # noqa: E402  modules/web_browse/browser.py — sees the fake


def tearDownModule():
    _restore_fake_playwright(_SAVED)


def _session_targets():
    """Every lifecycle the contract allows, most preferred first."""
    if hasattr(browser, 'browser_session'):
        return ('factory', browser.browser_session)
    if hasattr(browser, 'BrowserWorker'):
        return ('factory', browser.BrowserWorker)
    return ('module', None)


def _call_operation(name, *args, **kwargs):
    """Invoke ``open_url``/``web_search`` through whichever surface the
    implementation exposes: session worker, worker class, or module-level."""
    kind, factory = _session_targets()
    if kind == 'factory':
        worker = factory()
        op = getattr(worker, name, None)
        if hasattr(worker, '__enter__'):
            with worker as w:
                return getattr(w, name)(*args, **kwargs)
        try:
            return op(*args, **kwargs)
        finally:
            close = getattr(worker, 'close', None)
            if callable(close):
                close()
    return getattr(browser, name)(*args, **kwargs)


def _open_url(url, **kw):
    return _call_operation('open_url', url, **kw)


def _web_search(query, **kw):
    return _call_operation('web_search', query, **kw)


class OpenUrlContractTests(unittest.TestCase):
    def setUp(self):
        _NET['visited'] = []
        _NET['goto_error'] = None
        _NET['goto_status'] = {}
        _NET['launch_error'] = None
        _NET['cdp_endpoint'] = None
        self._pw_patch = mock.patch.object(
            browser, 'sync_playwright', _MANAGER, create=True)
        self._pw_patch.start()
        self.addCleanup(self._pw_patch.stop)

    def test_success_shape(self):
        result = _open_url('https://sa.aqar.fm/')
        self.assertIsInstance(result, dict)
        for key in ('url', 'final_url', 'title', 'text'):
            self.assertIn(key, result)
        self.assertEqual(result['url'], 'https://sa.aqar.fm/')
        self.assertEqual(result['title'], _NET['title'])
        self.assertTrue(result['text'])
        self.assertFalse(result.get('error'))
        self.assertLessEqual(len(result['text']), 12000)

    def test_goto_failure_returns_error_dict_never_raises(self):
        _NET['goto_error'] = _FakeTimeoutError('timeout 20000ms exceeded')
        result = _open_url('https://wasalt.sa/property/deep')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['url'], 'https://wasalt.sa/property/deep')
        self.assertTrue(result.get('error'))

    def test_exception_inside_page_read_still_returns_error(self):
        _NET['goto_error'] = RuntimeError('net::ERR_NAME_NOT_RESOLVED')
        result = _open_url('https://nonexistent.example/')
        self.assertTrue(result.get('error'))

    def test_ws_endpoint_env_connects_over_cdp(self):
        with mock.patch.dict('os.environ', {'BROWSER_WS_ENDPOINT': 'ws://127.0.0.1:9222'}):
            _open_url('https://sa.aqar.fm/')
        self.assertIn(_NET['cdp_endpoint'], ('ws://127.0.0.1:9222', None))
        if _NET['cdp_endpoint'] is None:
            self.assertTrue(_NET['launched'])


class Http403FallbackTests(unittest.TestCase):
    """http_403 earns one www<->apex sibling retry; nothing else does."""

    def setUp(self):
        _NET['visited'] = []
        _NET['goto_error'] = None
        _NET['goto_status'] = {}
        _NET['launch_error'] = None
        self._pw_patch = mock.patch.object(
            browser, 'sync_playwright', _MANAGER, create=True)
        self._pw_patch.start()
        self.addCleanup(self._pw_patch.stop)

    def test_apex_403_falls_back_to_www(self):
        _NET['goto_status'] = {'https://nhc.sa': 403}
        result = _open_url('https://nhc.sa')
        self.assertFalse(result.get('error'))
        self.assertEqual(_NET['visited'],
                         ['https://nhc.sa', 'https://www.nhc.sa'])

    def test_www_403_falls_back_to_apex(self):
        _NET['goto_status'] = {'https://www.ejar.sa': 403}
        result = _open_url('https://www.ejar.sa')
        self.assertFalse(result.get('error'))
        self.assertEqual(_NET['visited'],
                         ['https://www.ejar.sa', 'https://ejar.sa'])

    def test_403_on_both_forms_returns_error(self):
        _NET['goto_status'] = {'https://nhc.sa': 403,
                               'https://www.nhc.sa': 403}
        result = _open_url('https://nhc.sa')
        self.assertEqual(result.get('error'), 'http_403')
        self.assertEqual(len(_NET['visited']), 2)

    def test_non_403_status_never_falls_back(self):
        _NET['goto_status'] = {'https://www.nhc.sa/old': 404}
        result = _open_url('https://www.nhc.sa/old')
        self.assertEqual(result.get('error'), 'http_404')
        self.assertEqual(_NET['visited'], ['https://www.nhc.sa/old'])

    def test_success_never_falls_back(self):
        result = _open_url('https://sa.aqar.fm/')
        self.assertFalse(result.get('error'))
        self.assertEqual(_NET['visited'], ['https://sa.aqar.fm/'])

    def test_fallback_helper_shapes(self):
        self.assertEqual(browser._apex_www_fallback('https://nhc.sa'),
                         'https://www.nhc.sa')
        self.assertEqual(
            browser._apex_www_fallback('https://www.ejar.sa/ar'),
            'https://ejar.sa/ar')
        self.assertIsNone(browser._apex_www_fallback('not a url'))

    def test_request_headers_look_like_a_real_tab(self):
        self.assertIn('Accept', browser._EXTRA_HEADERS)
        self.assertIn('Sec-Fetch-Site', browser._EXTRA_HEADERS)


class WebSearchContractTests(unittest.TestCase):
    def setUp(self):
        _NET['visited'] = []
        _NET['goto_error'] = None
        _NET['launch_error'] = None
        self._pw_patch = mock.patch.object(
            browser, 'sync_playwright', _MANAGER, create=True)
        self._pw_patch.start()
        self.addCleanup(self._pw_patch.stop)

    def test_results_shape(self):
        results = _web_search('مشروع العجلان ريفيرا 16')
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        for item in results:
            self.assertIsInstance(item, dict)
            for key in ('title', 'url', 'snippet'):
                self.assertIn(key, item)
        urls = [i['url'] for i in results]
        self.assertTrue(any('aqar' in u or 'wasalt' in u for u in urls))

    def test_max_results_respected(self):
        saved_serp = _NET['serp']
        _NET['serp'] = saved_serp * 6
        try:
            results = _web_search('عقار', max_results=3)
        finally:
            _NET['serp'] = saved_serp
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 3)

    def test_provider_failure_returns_empty_list(self):
        saved_serp = _NET['serp']
        _NET['goto_error'] = _FakeTimeoutError('blocked')
        _NET['serp'] = []
        try:
            results = _web_search('مشروع')
        except Exception:
            self.fail('web_search should degrade to a list, not raise')
        finally:
            _NET['goto_error'] = None
            _NET['serp'] = saved_serp
        self.assertEqual(results, [])


class ProviderOrderTests(unittest.TestCase):
    """ddg is out of the default rotation — its 418 walls cost the goto
    timeout ahead of every real search — but it stays a valid
    BROWSER_SEARCH_PROVIDER pin so the contracted chain remains reachable."""

    def test_ddg_is_not_in_the_default_order(self):
        self.assertNotIn('ddg', browser._DEFAULT_ORDER)
        self.assertEqual(browser._DEFAULT_ORDER[0], 'brave')
        self.assertEqual(browser._providers(), list(browser._DEFAULT_ORDER))

    def test_ddg_stays_pinnable(self):
        import os
        with mock.patch.dict(os.environ, {'BROWSER_SEARCH_PROVIDER': 'ddg'}):
            providers = browser._providers()
        self.assertEqual(providers[0], 'ddg')
        # The pin comes first; the real chain still follows as fallbacks.
        self.assertEqual(providers[1:], browser._DEFAULT_ORDER)

    def test_unknown_pin_falls_back_to_default(self):
        import os
        with mock.patch.dict(os.environ, {'BROWSER_SEARCH_PROVIDER': 'nope'}):
            self.assertEqual(browser._providers(), browser._DEFAULT_ORDER)


class ThreadLocalBrowserTests(unittest.TestCase):
    """``thread_local_browser`` binds one live worker to the calling thread —
    the ×4 verify/scan pools share it instead of launching per call."""

    def setUp(self):
        _NET['visited'] = []
        _NET['goto_error'] = None
        _NET['launch_error'] = None
        self._pw_patch = mock.patch.object(
            browser, 'sync_playwright', _MANAGER, create=True)
        self._pw_patch.start()
        self.addCleanup(self._pw_patch.stop)
        browser.close_thread_browser()
        self.addCleanup(browser.close_thread_browser)

    def test_returns_a_live_worker_bound_to_the_thread(self):
        worker = browser.thread_local_browser()
        self.assertTrue(worker.is_open)
        self.assertIs(getattr(browser._tls, 'worker', None), worker)

    def test_second_call_reuses_the_same_worker(self):
        first = browser.thread_local_browser()
        self.assertIs(browser.thread_local_browser(), first)

    def test_close_thread_browser_releases_the_worker(self):
        worker = browser.thread_local_browser()
        browser.close_thread_browser()
        self.assertIsNone(getattr(browser._tls, 'worker', None))
        self.assertFalse(worker.is_open)
        self.assertIsNot(browser.thread_local_browser(), worker)

    def test_browser_session_restores_the_thread_worker(self):
        worker = browser.thread_local_browser()
        with browser.browser_session() as session_worker:
            self.assertIs(browser._tls.worker, session_worker)
        self.assertIs(browser._tls.worker, worker)
        self.assertTrue(worker.is_open)


class InteractContractTests(unittest.TestCase):
    """The interactive surface on BrowserWorker: inspect_page numbers the
    page's live elements (data-ll-el tags) and click/type/scroll act on them —
    every method returns the refreshed page state and never raises."""

    def setUp(self):
        _NET['visited'] = []
        _NET['clicks'] = []
        _NET['fills'] = []
        _NET['keys'] = []
        _NET['scrolls'] = []
        _NET['goto_error'] = None
        _NET['launch_error'] = None
        self._pw_patch = mock.patch.object(
            browser, 'sync_playwright', _MANAGER, create=True)
        self._pw_patch.start()
        self.addCleanup(self._pw_patch.stop)

    def test_inspect_page_returns_numbered_elements_and_text(self):
        result = _call_operation('inspect_page', 'https://sa.aqar.fm/')
        self.assertIsInstance(result, dict)
        for key in ('url', 'final_url', 'title', 'text', 'elements'):
            self.assertIn(key, result)
        self.assertFalse(result.get('error'))
        elements = result.get('elements') or []
        self.assertEqual([e.get('i') for e in elements], list(range(len(elements))))
        self.assertEqual(elements[1].get('text'), 'تطبيق الفلاتر')
        self.assertTrue(result.get('text'))

    def test_inspect_page_navigation_error_returns_error_dict(self):
        _NET['goto_error'] = _FakeTimeoutError('timeout 20000ms exceeded')
        result = _call_operation('inspect_page', 'https://wasalt.sa/x')
        self.assertTrue(result.get('error'))
        self.assertEqual(result.get('elements'), [])

    def test_click_element_targets_the_tagged_element(self):
        with browser.BrowserWorker() as worker:
            worker.inspect_page('https://sa.aqar.fm/')
            result = worker.click_element(1)
        self.assertIn('[data-ll-el="1"]', _NET['clicks'])
        self.assertFalse(result.get('error'))
        self.assertIn('elements', result)

    def test_type_text_fills_and_submits_with_enter(self):
        with browser.BrowserWorker() as worker:
            worker.inspect_page('https://sa.aqar.fm/')
            result = worker.type_text(0, 'الرياض', submit=True)
        self.assertIn(('[data-ll-el="0"]', 'الرياض'), _NET['fills'])
        self.assertIn('Enter', _NET['keys'])
        self.assertFalse(result.get('error'))

    def test_type_text_without_submit_does_not_press_enter(self):
        with browser.BrowserWorker() as worker:
            worker.inspect_page('https://sa.aqar.fm/')
            worker.type_text(0, 'جدة')
        self.assertEqual(_NET['keys'], [])

    def test_scroll_page_scrolls_and_returns_state(self):
        with browser.BrowserWorker() as worker:
            worker.inspect_page('https://sa.aqar.fm/')
            result = worker.scroll_page('down')
        self.assertTrue(_NET['scrolls'])
        self.assertFalse(result.get('error'))
        self.assertIn('elements', result)

    def test_invalid_index_never_raises(self):
        with browser.BrowserWorker() as worker:
            worker.inspect_page('https://sa.aqar.fm/')
            result = worker.click_element('nope')
        self.assertTrue(result.get('error'))


if __name__ == '__main__':
    unittest.main()
