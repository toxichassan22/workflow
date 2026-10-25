"""Headless-Chromium worker layer for the browse agents (task A1).

One Playwright browser per worker — the sync API is not thread-safe across
instances, so each agent thread opens its own session; there is deliberately
no module-level browser. Two entry points share the same worker:

- `BrowserWorker` / `browser_session()` — explicit lifecycle for the agent
  loop (lazily launched on first tool call, closed in `finally`). Beyond the
  read tools (`open_url`/`web_search`) the worker carries the interaction
  surface — `inspect_page` numbers the live DOM's elements and
  `click_element`/`type_text`/`scroll_page` act on them.
- `thread_local_browser()` / `close_thread_browser()` — a long-lived worker
  bound to the calling thread, for pools that run many fetches per thread.
- module-level `open_url()` / `web_search()` — contract helpers that reuse the
  calling thread's active session, or spin up a one-shot browser when none is.

`BROWSER_WS_ENDPOINT` (a CDP ws:// URL) replaces the local launch — the
fallback for hosts where Chromium cannot run (the A7 viability probe decides).
"""

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse

import booking_rooms
import booking_search
import hotel_stay

DEFAULT_TIMEOUT = 20        # seconds, page goto
BOOKING_TIMEOUT = 45        # Booking solves its WAF before DOMContentLoaded
SETTLE_MS = 1500            # post-domcontentloaded settle
TEXT_CAP = 12000            # chars kept per page
MAX_RESULTS = 8

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
ACCEPT_LANGUAGE = 'ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7'
VIEWPORT = {'width': 1366, 'height': 900}

# Full browser-like request headers. The context used to send only
# Accept-Language — many Saudi gov portals and Cloudflare-fronted hosts
# (http_403 in the market-study audit: sakani, ejar, mt, costar, str, jll)
# reject the bare automation profile, so every navigation carries the same
# header set a real Chromium tab would send on a top-level document load.
_EXTRA_HEADERS = {
    'Accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
               'image/avif,image/webp,*/*;q=0.8'),
    'Accept-Language': ACCEPT_LANGUAGE,
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}

_BLOCKED_TYPES = {'image', 'media', 'font'}
# Real Chrome solves Booking's AWS WAF challenge in a few seconds and reloads
# the page; a bundled Chromium never does. Wait long enough for the real page
# instead of marking the challenge shell as the final answer.
_CHALLENGE_WAIT_SECONDS = 15
_STRIP_SELECTOR = 'script,style,nav,footer,header,form,noscript,iframe'
# Booking pins the property on its map through this attribute; it is the only
# coordinate source a competitor distance filter can trust.
_COORDS_JS = """() => {
  const el = document.querySelector('[data-atlas-latlng]');
  return el ? (el.getAttribute('data-atlas-latlng') || '') : '';
}"""


def _booking_coords(page):
    try:
        raw = str(page.evaluate(_COORDS_JS) or '').strip()
    except Exception:
        return {}
    parts = [part.strip() for part in raw.split(',')]
    if len(parts) != 2:
        return {}
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return {}
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {}
    return {'lat': lat, 'lng': lng}
# SERP endpoints. Verified on this repo's dev box (2026-10): DDG's html/lite
# endpoints return an anomaly page (HTTP 418 body) from datacenter and dev IPs
# alike — a dead first provider that burned the goto timeout ahead of every
# real search, so it is out of the default rotation but stays a valid
# BROWSER_SEARCH_PROVIDER pin. bing.com works but its Arabic real-estate index
# returns SEO spam; search.brave.com and search.yahoo.com returned on-topic
# Saudi results for the probe query, so they carry real traffic.
_DDG_URL = 'https://html.duckduckgo.com/html/?q='
_BING_URL = 'https://www.bing.com/search?q='
_BRAVE_URL = 'https://search.brave.com/search?q='
_YAHOO_URL = 'https://search.yahoo.com/search?p='
# SERP pages get an en-US Accept-Language: ar-SA requests from automation-flagged
# IPs get degraded filler SERPs (or empty b_no pages) instead of the real index.
_SEARCH_LANG = 'en-US,en;q=0.9'

# Bot-wall detection: short page + captcha phrasing => 'blocked', which is
# more useful to the caller than an opaque http_ status on a 200 wall page.
_CAPTCHA_RE = re.compile(
    r'captcha|are you a robot|unusual traffic|anomaly|'
    r'just a moment|verify you are|attention required|security check|'
    r'challenge-platform|'
    r'لست روبوت|تحقق من أنك|رمز التحقق', re.I)

_EXTRACT_JS = """() => {
  for (const n of document.querySelectorAll('%s')) n.remove();
  const pick = document.querySelector('article')
    || document.querySelector('main')
    || document.querySelector('[role="main"]')
    || document.body;
  let t = (pick && pick.innerText) || '';
  if (!t.trim() && pick !== document.body)
    t = (document.body && document.body.innerText) || '';
  return t;
}""" % _STRIP_SELECTOR

_DDG_JS = """() => Array.from(document.querySelectorAll('.result')).map(r => {
  const a = r.querySelector('.result__a');
  const sn = r.querySelector('.result__snippet');
  return {title: a ? a.textContent.trim() : '',
          url: a ? a.href : '',
          snippet: sn ? sn.textContent.trim() : ''};
}).filter(r => r.url)"""

_BING_JS = """() => Array.from(document.querySelectorAll('li.b_algo')).map(r => {
  const a = r.querySelector('h2 a');
  const sn = r.querySelector('.b_caption p') || r.querySelector('.b_snippet');
  return {title: a ? a.textContent.trim() : '',
          url: a ? a.href : '',
          snippet: sn ? sn.textContent.trim() : ''};
}).filter(r => r.url)"""

_BRAVE_JS = """() => Array.from(
  document.querySelectorAll('div.snippet[data-type="web"]')).map(r => {
  const a = r.querySelector('a[href^="http"]');
  const t = r.querySelector('.snippet-title, .title, [class*="title"]');
  const sn = r.querySelector('.snippet-description, div.content, [class*="description"]');
  return {title: t ? t.textContent.trim() : (a ? a.textContent.trim() : ''),
          url: a ? a.href : '',
          snippet: sn ? sn.textContent.trim() : ''};
}).filter(r => r.url)"""

_YAHOO_JS = """() => Array.from(document.querySelectorAll('div.algo')).map(r => {
  const h = r.querySelector('h3.title');
  const a = r.querySelector('.compTitle a') || (h && h.closest('a'));
  const sn = r.querySelector('.compText');
  return {title: h ? h.textContent.trim() : (a ? a.textContent.trim() : ''),
          url: a ? a.href : '',
          snippet: sn ? sn.textContent.trim() : ''};
}).filter(r => r.url)"""

# --- Interactive surface -----------------------------------------------------
# The snapshot strips only non-interactive noise — nav/footer/forms stay,
# because menus, filters and search inputs live there (unlike _EXTRACT_JS,
# whose text-only job removes them). Every visible a/button/input/select/
# textarea is tagged data-ll-el="<n>" so click_element/type_text can aim at
# the number the model saw; a navigation wipes the tags, so indexes always
# belong to the latest snapshot.
_MAX_ELEMENTS = 40
_EL_ATTR = 'data-ll-el'
_SCROLL_DELTA = 720              # ~0.8 viewport at the 900px height
_SNAPSHOT_STRIP = 'script,style,noscript,iframe'
_SNAPSHOT_JS = """() => {
  for (const n of document.querySelectorAll('%s')) n.remove();
  const sel = 'a[href],button,input,select,textarea,summary,'
      + '[role="button"],[role="link"]';
  const elements = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r || r.width < 2 || r.height < 2) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    el.setAttribute('data-ll-el', String(i));
    const text = (el.innerText || el.value || el.getAttribute('aria-label')
        || el.getAttribute('placeholder') || el.name || '').trim().slice(0, 120);
    elements.push({i: i, tag: el.tagName.toLowerCase(),
                   type: el.getAttribute('type') || '',
                   text: text,
                   href: (el.tagName === 'A' ? (el.href || '') : ''),
                   placeholder: el.getAttribute('placeholder') || ''});
    if (++i >= %d) break;
  }
  const pick = document.querySelector('article')
    || document.querySelector('main')
    || document.querySelector('[role="main"]')
    || document.body;
  let t = (pick && pick.innerText) || '';
  if (!t.trim() && pick !== document.body)
    t = (document.body && document.body.innerText) || '';
  return {text: t, elements: elements};
}""" % (_SNAPSHOT_STRIP, _MAX_ELEMENTS)

_tls = threading.local()


def _clean_text(raw):
    text = re.sub(r'[ \t\r\f\v]+', ' ', raw or '')
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()[:TEXT_CAP]


_AWS_WAF_RE = re.compile(
    r'challenge-container|awsWafCookieDomainList|__challenge_', re.I)


def _challenge_shell(page):
    """True when the document is only an AWS WAF/JS challenge shell.

    Booking answers automation with a 200 page whose entire body is an empty
    ``challenge-container`` and an AWS WAF script; the visible text is empty,
    so the captcha wording check alone reads it as a successfully loaded page
    and every price/room field silently stays blank. A real Chrome solves the
    challenge in a couple of seconds and reloads; ``content()`` fails while
    that navigation is in flight, which still means «not the real page yet».
    """
    try:
        html = page.content()
    except Exception:
        return True
    return bool(_AWS_WAF_RE.search(html or ''))


def _looks_blocked(title, text):
    return len(text) < 1500 and bool(_CAPTCHA_RE.search(f'{title}\n{text[:800]}'))


def _nav_reason(exc):
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if 'timeout' in name or 'timeout' in msg:
        return 'timeout'
    match = re.search(r'net::([a-z_0-9]+)', msg)
    if match:
        return match.group(1)
    if 'invalid' in msg or 'cannot navigate' in msg:
        return 'invalid_url'
    return name or 'navigation_failed'


def _launch_reason(exc):
    if isinstance(exc, ImportError):
        return 'playwright_not_installed'
    msg = str(exc).lower()
    if 'executable' in msg or 'playwright install' in msg:
        return 'browser_not_installed'
    return 'launch_failed'


def _result(url):
    return {'url': url, 'final_url': url, 'title': '', 'text': '', 'error': None}


def _apex_www_fallback(url):
    """The www<->apex sibling of `url`, or None when it has no such form.

    Measured in the market-study audit: nhc.sa answers http_403 while
    www.nhc.sa serves the same content — one host form rejecting automation
    does not mean its sibling does, so a 403 earns one sibling retry."""
    try:
        parsed = urlparse(str(url or '').strip())
        host = (parsed.hostname or '').lower()
        if not host or parsed.scheme.lower() not in ('http', 'https'):
            return None
        sibling = host[4:] if host.startswith('www.') else 'www.' + host
        netloc = sibling
        if parsed.port:
            netloc += f':{parsed.port}'
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f':{parsed.password}'
            netloc = f'{auth}@{netloc}'
        return parsed._replace(netloc=netloc).geturl()
    except Exception:
        return None


def _unwrap_ddg(href):
    if 'uddg=' in href:
        target = (parse_qs(urlparse(href).query).get('uddg') or [''])[0]
        if target:
            return unquote(target)
    return href


def _unwrap_bing(href):
    # Bing wraps result links as bing.com/ck/a?...&u=a1<base64url(real url)>
    target = (parse_qs(urlparse(href).query).get('u') or [''])[0]
    if target.startswith('a1'):
        payload = target[2:] + '=' * (-len(target[2:]) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload).decode('utf-8', 'replace')
        except Exception:
            return href
        if decoded.startswith('http'):
            return decoded
    return href


def _unwrap_yahoo(href):
    # Some placements wrap the target as r.search.yahoo.com/.../RU=<url>/RK=...
    if 'r.search.yahoo.com' in href:
        match = re.search(r'/RU=([^/]+)', href)
        if match:
            return unquote(match.group(1))
    return href


def _search_url(provider, query, cap):
    q = quote_plus(str(query))
    if provider == 'ddg':
        return _DDG_URL + q
    if provider == 'bing':
        return _BING_URL + q + '&count=' + str(cap)
    if provider == 'brave':
        return _BRAVE_URL + q + '&source=web'
    return _YAHOO_URL + q


_PROVIDER_JS = {'ddg': _DDG_JS, 'bing': _BING_JS,
                'brave': _BRAVE_JS, 'yahoo': _YAHOO_JS}

_PROVIDER_UNWRAP = {'ddg': _unwrap_ddg, 'bing': _unwrap_bing,
                    'yahoo': _unwrap_yahoo}

# brave/yahoo first — verified relevant on Arabic real-estate queries; bing
# last (non-empty but spam-grade). ddg is out of the default rotation: its
# 418 anomaly pages cost the goto timeout before every real search. It stays
# a valid BROWSER_SEARCH_PROVIDER pin so tests can force the old chain.
_DEFAULT_ORDER = ['brave', 'yahoo', 'bing']


def _browser_log(message):
    """Keep browser diagnostics from breaking searches on non-UTF consoles."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(str(message).encode('ascii', 'backslashreplace').decode('ascii'))

# Self-hosted metasearch: SEARXNG_URL points at a SearXNG instance (its JSON
# format must be enabled in settings.yml). When configured it leads the
# order — one local HTTP call beats three walled SERP scrapes — and
# BROWSER_SEARCH_PROVIDER=searxng pins it explicitly.
_SEARXNG_TIMEOUT = 8


def _searxng_base():
    return (os.environ.get('SEARXNG_URL') or '').strip().rstrip('/')


def _searxng_search(query, cap):
    """Plain-HTTP call into the self-hosted metasearch — no page needed."""
    base = _searxng_base()
    if not base:
        return []
    url = (base + '/search?' + urlencode({
        'q': str(query), 'format': 'json',
        'language': 'auto', 'safesearch': '0'}))
    try:
        req = urllib.request.Request(
            url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
        payload = json.loads(
            urllib.request.urlopen(req, timeout=_SEARXNG_TIMEOUT).read() or b'{}')
    except Exception as exc:
        _browser_log(f'[BROWSER] searxng failed: {exc}')
        return []
    hits = []
    for row in payload.get('results') or []:
        if not isinstance(row, dict):
            continue
        link = str(row.get('url') or '').strip()
        title = str(row.get('title') or '').strip()
        if not link or not title:
            continue
        hits.append({'title': title, 'url': link,
                     'snippet': str(row.get('content') or '').strip()})
        if len(hits) >= cap:
            break
    return hits


def _providers(search_provider=None):
    forced = str(search_provider or '').strip().lower()
    if forced:
        if forced == 'searxng':
            # A dead or empty local endpoint must not turn every market search
            # into a miss. Keep the query and continue through browser SERPs.
            preferred = ['searxng'] if _searxng_base() else []
            return preferred + list(_DEFAULT_ORDER)
        return [forced]
    pinned = (os.environ.get('BROWSER_SEARCH_PROVIDER') or '').strip().lower()
    order = list(_DEFAULT_ORDER)
    if _searxng_base():
        order.insert(0, 'searxng')
    if pinned in _PROVIDER_JS or (pinned == 'searxng' and _searxng_base()):
        # A known provider pins first — including ddg, which is no longer in
        # the default order but must stay reachable for tests/contracts.
        order = [pinned] + [p for p in order if p != pinned]
    return order


def _active_worker():
    worker = getattr(_tls, 'worker', None)
    return worker if worker is not None and worker.is_open else None


def _managed_chrome_executable():
    """The real Chrome/Chromium binary for the direct-CDP launch.

    BROWSER_EXECUTABLE_PATH is explicit and wins; a missing explicit path is
    not silently replaced. Otherwise a managed binary is auto-detected unless
    BROWSER_MANAGED_CHROME=0 disables it. Google Chrome is preferred, and the
    bundled Playwright Chromium is accepted too: launching it directly over
    CDP is what gets Booking past the WAF, not Playwright's own launch flags.
    """
    explicit = (os.environ.get('BROWSER_EXECUTABLE_PATH') or '').strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else ''
    if (os.environ.get('BROWSER_MANAGED_CHROME') or '').strip().lower() in (
            '0', 'false', 'no', 'off'):
        return ''
    candidates = [
        shutil.which('google-chrome'),
        shutil.which('google-chrome-stable'),
        shutil.which('chrome'),
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/opt/google/chrome/chrome',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]
    for pattern in (
            os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome'),
            os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux/chrome'),
            os.path.expanduser('~/AppData/Local/ms-playwright/chromium-*/chrome-win*/chrome.exe')):
        candidates.extend(sorted(glob.glob(pattern), reverse=True))
    return next((path for path in candidates if path and os.path.isfile(path)), '')


def _stop_managed_chrome(proc, profile):
    try:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
    finally:
        if profile:
            shutil.rmtree(profile, ignore_errors=True)


def _start_managed_chrome(executable, headless=True):
    """Launch real Chrome with its own profile and a CDP endpoint.

    The default context of this browser is the one Booking's WAF accepts;
    Playwright's browser launch and its incognito contexts are challenged.
    """
    profile = tempfile.mkdtemp(prefix='wf-chrome-')
    flags = [executable]
    if headless:
        flags.append('--headless=new')
    flags.extend([
        '--remote-debugging-port=0',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--disable-dev-shm-usage',
    ])
    flags.extend((os.environ.get('BROWSER_LAUNCH_ARGS') or '').split())
    flags.append('about:blank')
    proc = subprocess.Popen(flags, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    port_file = os.path.join(profile, 'DevToolsActivePort')
    port = None
    for _ in range(150):
        if proc.poll() is not None:
            break
        try:
            with open(port_file, encoding='utf-8') as handle:
                line = handle.readline().strip()
            port = int(line) if line else None
        except (OSError, ValueError):
            port = None
        if port:
            break
        time.sleep(0.1)
    if not port:
        _stop_managed_chrome(proc, profile)
        raise RuntimeError('managed Chrome did not expose a DevTools port')
    return proc, profile, port


class BrowserWorker:
    """One headless Chromium + page, bound to the thread that opened it."""

    def __init__(self, headless=True, search_provider=None):
        if os.environ.get('BROWSER_HEADLESS') == '0':
            headless = False
        self.headless = headless
        self.search_provider = str(search_provider or '').strip().lower() or None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._chrome_proc = None
        self._chrome_profile = ''
        self._using_cdp = False
        self.is_open = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()
        return False

    def start(self):
        if self.is_open and self._page is not None and not self._page.is_closed():
            return self
        self.close()   # drop any half-open driver before relaunching
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        endpoint = (os.environ.get('BROWSER_WS_ENDPOINT') or '').strip()
        executable = _managed_chrome_executable()
        using_cdp = False
        if endpoint:
            self._browser = self._pw.chromium.connect_over_cdp(endpoint)
            print('[BROWSER] launch mode=cdp')
            using_cdp = True
        elif executable:
            self._chrome_proc, self._chrome_profile, port = _start_managed_chrome(
                executable, headless=self.headless)
            self._browser = self._pw.chromium.connect_over_cdp(
                f'http://127.0.0.1:{port}')
            print(f'[BROWSER] launch mode=managed-chrome path={executable}')
            using_cdp = True
        else:
            args = ['--disable-dev-shm-usage']
            extra = (os.environ.get('BROWSER_LAUNCH_ARGS') or '').split()
            self._browser = self._pw.chromium.launch(
                headless=self.headless, args=args + extra)
            print('[BROWSER] launch mode=local browser=chromium')
        self._using_cdp = using_cdp
        if using_cdp and getattr(self._browser, 'contexts', None):
            # The browser's default context is a real profile; a fresh
            # incognito context is what Booking's WAF challenges.
            self._context = self._browser.contexts[0]
        else:
            try:
                self._context = self._browser.new_context(
                    user_agent=USER_AGENT, locale='ar-SA', viewport=VIEWPORT,
                    bypass_csp=False,
                    extra_http_headers=dict(_EXTRA_HEADERS))
            except Exception:
                # Some CDP endpoints only expose their default context.
                self._context = (self._browser.contexts or [None])[0]
                if self._context is None:
                    raise
        if not using_cdp:
            # The resource-blocking route is fine for the bundled Chromium, but
            # it can starve a real Chrome's WAF challenge; CDP contexts keep
            # their normal resource loading.
            self._context.route('**/*', self._route)
        self._page = self._context.new_page()
        self.is_open = True
        return self

    def close(self):
        for closable in (self._context, self._browser):
            try:
                if closable is not None:
                    closable.close()
            except Exception:
                pass
        self._context = self._browser = self._page = None
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        proc, profile = self._chrome_proc, self._chrome_profile
        self._chrome_proc, self._chrome_profile = None, ''
        _stop_managed_chrome(proc, profile)
        self._pw = None
        self.is_open = False

    @staticmethod
    def _route(route):
        try:
            if route.request.resource_type in _BLOCKED_TYPES:
                route.abort()
            else:
                route.continue_()
        except Exception:
            pass

    def _ensure_page(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        self.close()
        self.start()
        return self._page

    def _open_url_once(self, page, url, timeout):
        """One goto+extract attempt; never raises."""
        result = _result(url)
        is_booking = hotel_stay.is_booking_hotel_url(url)
        is_booking_search = booking_search.is_booking_search_url(url)
        if getattr(self, '_using_cdp', False):
            # The managed browser runs headless; without a desktop UA every
            # protected site (Booking and the property portals alike) answers
            # «HeadlessChrome» with a challenge or a 403.
            error = booking_rooms.apply_user_agent(
                page, USER_AGENT, ACCEPT_LANGUAGE)
            if error:
                _browser_log(f'[BROWSER] UA override failed: {error}')
        if not getattr(self, '_using_cdp', False):
            try:
                page.set_extra_http_headers(dict(_EXTRA_HEADERS))
            except Exception:
                pass
        try:
            response = page.goto(str(url), wait_until='domcontentloaded',
                                 timeout=int(timeout * 1000))
            page.wait_for_timeout(SETTLE_MS)
            if is_booking and getattr(self, '_using_cdp', False):
                booking_rooms.wait_for_rate_rows(
                    page, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
            elif is_booking_search and getattr(self, '_using_cdp', False):
                booking_search.wait_for_property_cards(
                    page, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
        except Exception as exc:
            # Navigation failed — whatever is in the page now is leftover state
            # from the previous call, not this URL's content. Do not return it.
            result['error'] = _nav_reason(exc)
            return result
        # Read the room table before _EXTRACT_JS strips forms — Booking wraps
        # the availability table in a form, so extracting afterwards sees none.
        if is_booking:
            rate = booking_rooms.wait_and_extract(page, url)
            if rate:
                result['booking_rate'] = rate
            coords = _booking_coords(page)
            if coords:
                result['booking_coords'] = coords
        elif is_booking_search:
            districts = booking_search.extract_district_facets(page)
            if districts:
                result['booking_districts'] = districts
            search = booking_search.extract_search_results(page)
            if search:
                result['booking_search'] = search
        try:
            result['final_url'] = page.url or url
            result['title'] = page.title() or ''
            result['text'] = _clean_text(page.evaluate(_EXTRACT_JS))
        except Exception:
            pass
        # Only a real Chrome attached over CDP can solve the WAF challenge;
        # waiting on the bundled Chromium just burns the job's budget.
        if (len(result['text'] or '') < 1500
                and getattr(self, '_using_cdp', False)
                and _challenge_shell(page)):
            deadline = time.time() + _CHALLENGE_WAIT_SECONDS
            previous = result['text'] or ''
            stable = 0
            while time.time() < deadline:
                try:
                    page.wait_for_timeout(1000)
                    result['final_url'] = page.url or url
                    result['title'] = page.title() or ''
                    result['text'] = _clean_text(page.evaluate(_EXTRACT_JS))
                except Exception:
                    continue
                if _challenge_shell(page):
                    stable = 0
                    continue
                if (result['text'] or '') == previous:
                    stable += 1
                else:
                    stable = 0
                    previous = result['text'] or ''
                # The real page may still be painting its first small shell;
                # wait one quiet second before accepting a short result.
                if (result['text'] or '').strip() and stable >= 1:
                    break
        status = getattr(response, 'status', None)
        if status is not None and status >= 400:
            result['error'] = f'http_{status}'
        elif (_looks_blocked(result['title'], result['text'])
              or (len(result['text']) < 1500 and _challenge_shell(page))):
            result['error'] = 'blocked'
        if (is_booking and not result.get('error')
                and result.get('booking_rate')):
            result['text'] = booking_rooms.with_rate_block(
                result['booking_rate'], result.get('text'))
        elif (is_booking_search and not result.get('error')
                and result.get('booking_search')):
            result['text'] = booking_search.with_search_block(
                result['booking_search'], result.get('text'))
        return result

    def fetch_html(self, url, timeout=DEFAULT_TIMEOUT):
        """Navigate and return the page's raw HTML (links included).

        Booking's destination resolution needs the hrefs on a content page,
        which the readable-text extraction strips. Never raises.
        """
        result = {'url': str(url or ''), 'final_url': '', 'html': '',
                  'status': None, 'error': ''}
        try:
            page = self._ensure_page()
        except Exception as exc:
            result['error'] = _launch_reason(exc)
            return result
        if getattr(self, '_using_cdp', False):
            # The managed browser runs headless; the portals (aqar, bayut,
            # wasalt) answer its HeadlessChrome UA with a block page even
            # when open_url would pass. The override belongs on every
            # navigation, not just the readable-text path.
            error = booking_rooms.apply_user_agent(
                page, USER_AGENT, ACCEPT_LANGUAGE)
            if error:
                _browser_log(f'[BROWSER] UA override failed: {error}')
        try:
            response = page.goto(str(url), wait_until='domcontentloaded',
                                 timeout=int(timeout * 1000))
            page.wait_for_timeout(SETTLE_MS)
            result['status'] = getattr(response, 'status', None)
            result['final_url'] = page.url or str(url)
            result['html'] = page.content() or ''
        except Exception as exc:
            result['error'] = _nav_reason(exc)
        return result

    def open_urls(self, urls, timeout=BOOKING_TIMEOUT):
        """Open Booking property pages in parallel tabs, then read them.

        Every tab starts loading at once, so the WAF and the room-table paint
        of one hotel overlap the next one's instead of adding up. One result
        per URL, in the input order.
        """
        urls = [str(url or '') for url in urls]
        results = [_result(url) for url in urls]
        try:
            self._ensure_page()
        except Exception as exc:
            for result in results:
                result['error'] = _launch_reason(exc)
            return results
        tabs = []
        for index, url in enumerate(urls):
            stay_url = hotel_stay.with_booking_stay_params(url)
            results[index]['url'] = stay_url
            try:
                tab = self._context.new_page()
            except Exception as exc:
                results[index]['error'] = _nav_reason(exc)
                continue
            tabs.append((index, tab, stay_url))
            error = booking_rooms.apply_user_agent(
                tab, USER_AGENT, ACCEPT_LANGUAGE)
            if error:
                _browser_log(f'[BROWSER] booking UA override failed: {error}')
            try:
                tab.goto(stay_url, wait_until='commit',
                         timeout=int(timeout * 1000))
            except Exception as exc:
                results[index]['error'] = _nav_reason(exc)
        for index, tab, url in tabs:
            result = results[index]
            started = time.time()
            try:
                if not result.get('error'):
                    booking_rooms.wait_for_rate_rows(
                        tab, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
                    rate = booking_rooms.wait_and_extract(tab, url)
                    if rate:
                        result['booking_rate'] = rate
                    coords = _booking_coords(tab)
                    if coords:
                        result['booking_coords'] = coords
                    result['final_url'] = tab.url or url
                    result['title'] = tab.title() or ''
                    result['text'] = _clean_text(tab.evaluate(_EXTRACT_JS))
                    if rate:
                        result['text'] = booking_rooms.with_rate_block(
                            rate, result.get('text'))
                else:
                    result['final_url'] = tab.url or url
            except Exception as exc:
                result['error'] = result.get('error') or _nav_reason(exc)
            finally:
                result['elapsed'] = round(time.time() - started, 1)
                try:
                    tab.close()
                except Exception:
                    pass
        return results

    def open_url(self, url, timeout=DEFAULT_TIMEOUT):
        """Load `url` and extract readable text; never raises.

        On http_403 exactly, one retry goes to the www<->apex sibling before
        giving up — a host form rejecting automation does not condemn its
        sibling, and the sibling answer is pooled upstream like any page.
        """
        stay_url = hotel_stay.with_booking_stay_params(url)
        if stay_url != url:
            _browser_log(f'[BROWSER] booking stay window applied: {stay_url}')
            url = stay_url
        if (hotel_stay.is_booking_hotel_url(url)
                or booking_search.is_booking_search_url(url)):
            # Booking's WAF runs before the document is complete; the default
            # window cut real property pages off mid-challenge.
            timeout = max(int(timeout or 0), BOOKING_TIMEOUT)
        result = _result(url)
        try:
            page = self._ensure_page()
        except Exception as exc:
            result['error'] = _launch_reason(exc)
            return result
        result = self._open_url_once(page, url, timeout)
        if result.get('error') == 'http_403':
            fallback = _apex_www_fallback(url)
            if fallback and fallback != url:
                _browser_log(f'[BROWSER] http_403, retrying sibling host: {fallback}')
                result = self._open_url_once(page, fallback, timeout)
        elif (result.get('error') == 'timeout'
              and (hotel_stay.is_booking_hotel_url(url)
                   or booking_search.is_booking_search_url(url))):
            # The competitor job opens several browsers at once; a heavy
            # Booking page can miss one navigation window without being a
            # real failure, and a lost page would drop its hotels.
            _browser_log(f'[BROWSER] booking timeout, retrying once: {url}')
            result = self._open_url_once(page, url, timeout)
        return result

    def web_search(self, query, max_results=MAX_RESULTS):
        """SERP scrape: tries each provider in order until hits; never raises.
        A provider that serves a bot wall twice in a row is skipped for the
        rest of the session — its goto+settle seconds are pure cost."""
        cap = max(1, int(max_results or MAX_RESULTS))
        for provider in _providers(getattr(self, 'search_provider', None)):
            if provider in getattr(self, '_blocked_serps', ()):
                continue
            try:
                hits = self._search_once(provider, query, cap)
            except Exception as exc:
                _browser_log(f'[BROWSER] search provider={provider} failed: {exc}')
                hits = []
            if hits:
                _browser_log(f'[BROWSER] search provider={provider} hits={len(hits)}')
                return hits
            title, walled = (('', False) if provider == 'searxng'
                             else self._serp_state())
            if walled:
                streaks = getattr(self, '_serp_block_streak', None)
                if streaks is None:
                    streaks = self._serp_block_streak = {}
                streaks[provider] = streaks.get(provider, 0) + 1
                _browser_log(f"[BROWSER] search provider={provider} blocked (bot wall) title={title!r}")
                if streaks[provider] >= 2:
                    blocked = getattr(self, '_blocked_serps', None)
                    if blocked is None:
                        blocked = self._blocked_serps = set()
                    blocked.add(provider)
                    _browser_log(f'[BROWSER] search provider={provider} skipped for this session')
                continue
            _browser_log(f"[BROWSER] search provider={provider} hits=0 title={title!r}")
        return []

    def _serp_state(self):
        """(title, walled) of the already-loaded SERP — only consulted when
        the extractor found no rows, so a real empty result page stays a
        'hits=0' log line while a captcha/anomaly/challenge page reports
        'blocked'. The title rides every line so a new wall shape or a
        changed SERP markup shows up in the log instead of vanishing."""
        try:
            title = self._page.title() if self._page is not None else ''
            text = self._page.evaluate(
                "() => document.body ? document.body.innerText.slice(0, 900) : ''")
        except Exception:
            return '', False
        title = str(title or '')[:120]
        return title, _looks_blocked(title, str(text or ''))

    def _search_once(self, provider, query, cap):
        if provider == 'searxng':
            return _searxng_search(query, cap)
        page = self._ensure_page()
        # SERPs get en-US headers — see _SEARCH_LANG. Page reads keep ar-SA.
        try:
            page.set_extra_http_headers({'Accept-Language': _SEARCH_LANG})
        except Exception:
            pass
        page.goto(_search_url(provider, query, cap),
                  wait_until='domcontentloaded',
                  timeout=int(DEFAULT_TIMEOUT * 1000))
        page.wait_for_timeout(SETTLE_MS)
        hits = []
        for row in page.evaluate(_PROVIDER_JS[provider]) or []:
            link = (_PROVIDER_UNWRAP.get(provider) or (lambda h: h))(
                row.get('url') or '')
            title = (row.get('title') or '').strip()
            if not link or not title:
                continue
            hits.append({'title': title, 'url': link,
                         'snippet': (row.get('snippet') or '').strip()})
            if len(hits) >= cap:
                break
        return hits

    # ------------------------------------------------------------------
    # Interaction tools — "use" the page, not just read it. Every method
    # answers with the refreshed page state ({url, final_url, title, text,
    # elements, error}) so the agent sees the effect, and never raises.
    # Element indexes are the data-ll-el tags left by the latest snapshot.
    # ------------------------------------------------------------------
    def _snapshot(self, page):
        try:
            data = page.evaluate(_SNAPSHOT_JS)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _state(self, page, url=''):
        try:
            final_url = page.url or url
            title = page.title() or ''
        except Exception:
            final_url, title = url or '', ''
        snap = self._snapshot(page)
        return {'url': url or final_url,
                'final_url': final_url,
                'title': title,
                'text': _clean_text(snap.get('text') or ''),
                'elements': snap.get('elements') or [],
                'error': None}

    @staticmethod
    def _state_error(url, reason):
        return {'url': url or '', 'final_url': url or '', 'title': '',
                'text': '', 'elements': [], 'error': reason}

    def inspect_page(self, url=None, timeout=DEFAULT_TIMEOUT):
        """Numbered-elements snapshot. ``url`` opens the page through
        open_url first (bot walls still surface as 'blocked'); omitted, it
        snapshots the page the worker is already on. Never raises."""
        if url:
            opened = self.open_url(url, timeout=timeout)
            if opened.get('error'):
                opened['elements'] = []
                return opened
        try:
            page = self._ensure_page()
        except Exception as exc:
            return self._state_error(url, _launch_reason(exc))
        state = self._state(page, str(url or ''))
        if (_looks_blocked(state['title'], state['text'])
                or (len(state['text'] or '') < 1500 and _challenge_shell(page))):
            state['error'] = 'blocked'
        return state

    def _element_action(self, index, act):
        """Shared shell for click/fill: resolve the page, run ``act`` on the
        tagged selector, settle, and return the refreshed state."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return self._state_error('', 'invalid_index')
        try:
            page = self._ensure_page()
        except Exception as exc:
            return self._state_error('', _launch_reason(exc))
        try:
            act(page, f'[{_EL_ATTR}="{index}"]')
            page.wait_for_timeout(SETTLE_MS)
        except Exception as exc:
            state = self._state(page)
            state['error'] = _nav_reason(exc)
            return state
        return self._state(page)

    def click_element(self, index):
        """Click element #index from the latest snapshot. Never raises."""
        return self._element_action(
            index, lambda page, sel: page.click(sel, timeout=5000))

    def type_text(self, index, text, submit=False):
        """Fill input #index with ``text``; ``submit`` presses Enter after
        (site search boxes). Never raises."""
        def act(page, sel):
            page.fill(sel, str(text or ''), timeout=5000)
            if submit:
                page.keyboard.press('Enter')
        return self._element_action(index, act)

    def scroll_page(self, direction='down'):
        """Scroll the live page ~one viewport ('down' default, 'up' back) —
        lazy-loaded listings. Never raises."""
        try:
            page = self._ensure_page()
        except Exception as exc:
            return self._state_error('', _launch_reason(exc))
        delta = -_SCROLL_DELTA if str(direction).strip().lower() == 'up' else _SCROLL_DELTA
        try:
            page.evaluate("(dy) => window.scrollBy(0, dy)", delta)
            page.wait_for_timeout(SETTLE_MS)
        except Exception as exc:
            state = self._state(page)
            state['error'] = _nav_reason(exc)
            return state
        return self._state(page)


def thread_local_browser(headless=True, search_provider=None):
    """The calling thread's shared worker — a live BrowserWorker bound via
    ``_tls.worker``.

    Pool threads (the ×4 verify/scan pools) take one worker per thread and
    reuse it for every fetch instead of paying a Chromium launch per call.
    Reuses the already-active worker when the thread has one (an open
    ``browser_session()`` included); ``close_thread_browser()`` releases it
    when the pool shuts down.
    """
    worker = _active_worker()
    requested_provider = str(search_provider or '').strip().lower() or None
    if worker is not None and getattr(worker, 'search_provider', None) != requested_provider:
        try:
            worker.close()
        except Exception:
            pass
        worker = None
    if worker is None:
        stale = getattr(_tls, 'worker', None)
        if stale is not None:
            try:
                stale.close()
            except Exception:
                pass
        worker = BrowserWorker(headless=headless, search_provider=requested_provider)
        worker.start()
        _tls.worker = worker
    return worker


def close_thread_browser():
    """Release the calling thread's shared worker, if one was bound."""
    worker = getattr(_tls, 'worker', None)
    _tls.worker = None
    if worker is not None:
        try:
            worker.close()
        except Exception:
            pass


@contextmanager
def browser_session(headless=True, search_provider=None):
    """The per-agent-run session: one browser for the calling thread."""
    worker = BrowserWorker(headless=headless, search_provider=search_provider)
    previous = getattr(_tls, 'worker', None)
    try:
        worker.start()
        _tls.worker = worker
        yield worker
    finally:
        if getattr(_tls, 'worker', None) is worker:
            # Hand the slot back to a thread worker that was bound earlier —
            # the session only borrows it for its own lifetime.
            _tls.worker = previous
        worker.close()


def open_url(url, timeout=DEFAULT_TIMEOUT):
    """Contract helper — reuses this thread's session, else a one-shot run."""
    try:
        worker = _active_worker()
        if worker is not None:
            return worker.open_url(url, timeout=timeout)
        with BrowserWorker() as one_shot:
            return one_shot.open_url(url, timeout=timeout)
    except Exception as exc:
        result = _result(url)
        result['error'] = _launch_reason(exc)
        return result


def web_search(query, max_results=MAX_RESULTS):
    """Contract helper — reuses this thread's session, else a one-shot run."""
    try:
        worker = _active_worker()
        if worker is not None:
            return worker.web_search(query, max_results=max_results)
        with BrowserWorker() as one_shot:
            return one_shot.web_search(query, max_results=max_results)
    except Exception:
        return []
