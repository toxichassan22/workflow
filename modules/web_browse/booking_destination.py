"""Resolve a project's city to Booking's own destination id.

Booking no longer resolves a free-text ``ss`` search: the request is answered
with a redirect to the homepage carrying ``errorc_searchstring_not_found=ss``.
That was measured on 2026-10-24 from a residential IP as well as from the
staging host, and the destination autocomplete endpoint answers 403, so the
only deterministic route left is Booking's own content pages:

    country page (lists every city) -> city page -> ``dest_id``

The search then runs on ``dest_id`` + ``dest_type`` alone; the district comes
from Booking's neighbourhood filter (see ``booking_search``).
"""

import json
import os
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import booking_search

COUNTRY_PAGE_URL = 'https://www.booking.com/country/{country}.html?lang={lang}'
COUNTRY_LANGS = ('en-us', 'ar')
BOOKING_ORIGIN = 'https://www.booking.com'
CONTENT_PAGE_TIMEOUT = 45
CONTENT_PAGE_ATTEMPTS = 2
CONTENT_PAGE_RETRY_DELAY = 1.5
CACHE_TTL_SECONDS = 30 * 24 * 3600
CACHE_FILE_NAME = '.booking_destinations.json'
_CITY_PATH_RE = re.compile(r'^/city/([a-z]{2})/[a-z0-9\-]+\.html$', re.I)
_DEST_INPUT_RE = re.compile(
    r'name=["\']dest_id["\'][^>]*value=["\'](-?\d+)["\']', re.I)
_DEST_PARAM_RE = re.compile(r'[?&]dest_id=(-?\d+)')
_DEST_TYPE_RE = re.compile(r'[?&]dest_type=([a-z]+)|'
                           r'name=["\']dest_type["\'][^>]*value=["\']([a-z]+)["\']',
                           re.I)

_RESOLVED = {}
_LOCK = threading.Lock()


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._href = dict(attrs).get('href') or ''
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            text = ' '.join(''.join(self._text).split())
            self.links.append({'href': self._href, 'text': text})
            self._href = None


def country_page_url(country_code, lang='en-us'):
    return COUNTRY_PAGE_URL.format(country=country_code, lang=lang)


def normalize_country_code(value):
    return re.sub(r'[^a-z]', '', str(value or '').casefold())[:2]


def anchors(html):
    parser = _AnchorParser()
    try:
        parser.feed(str(html or ''))
        parser.close()
    except Exception:
        return []
    return parser.links


def city_links(html):
    """Every city-page link on a country page, as absolute URLs."""
    links = []
    for anchor in anchors(html):
        href = str(anchor.get('href') or '').strip()
        if not href:
            continue
        absolute = urljoin(BOOKING_ORIGIN, href)
        if _CITY_PATH_RE.match(urlsplit(absolute).path):
            links.append({'url': absolute, 'text': anchor.get('text') or ''})
    return links


def pick_city_link(html, *names):
    """The country-page link whose label names one of ``names``."""
    wanted = [booking_search.normalize_label(name) for name in names]
    wanted = [name for name in wanted if name]
    if not wanted:
        return ''
    for link in city_links(html):
        label = booking_search.normalize_label(link.get('text'))
        if not label:
            continue
        for name in wanted:
            if label == name or label.startswith(name):
                return link['url']
    return ''


def parse_destination(html):
    """``dest_id`` / ``dest_type`` from a Booking city page."""
    text = str(html or '')
    match = _DEST_INPUT_RE.search(text) or _DEST_PARAM_RE.search(text)
    if not match:
        return {}
    dest_type = 'city'
    type_match = _DEST_TYPE_RE.search(text)
    if type_match:
        dest_type = (type_match.group(1) or type_match.group(2) or 'city').lower()
    return {'dest_id': match.group(1), 'dest_type': dest_type}


def _fetch(session, url, predicate=None):
    """Fetch a Booking content page, retrying: the pages are heavy, the
    competitor job opens several browsers at once, and a page can arrive
    without its links even when the navigation itself succeeded."""
    page = {}
    for attempt in range(max(1, CONTENT_PAGE_ATTEMPTS)):
        page = session.fetch_html(url, timeout=CONTENT_PAGE_TIMEOUT)
        if isinstance(page, dict) and page.get('html') and not page.get('error'):
            if predicate is None or predicate(page.get('html') or ''):
                return page
        if attempt + 1 < CONTENT_PAGE_ATTEMPTS:
            time.sleep(CONTENT_PAGE_RETRY_DELAY)
    return page if isinstance(page, dict) else {}


def _cache_read(cache_path):
    if not cache_path or not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cache_write(cache_path, payload):
    if not cache_path:
        return
    try:
        folder = os.path.dirname(cache_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temp = f'{cache_path}.{os.getpid()}.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temp, cache_path)
    except Exception:
        pass


def _cache_lookup(cache_path, key):
    entry = _cache_read(cache_path).get(key)
    if not isinstance(entry, dict):
        return {}
    saved_at = entry.get('saved_at')
    if isinstance(saved_at, (int, float)) and (
            time.time() - saved_at > CACHE_TTL_SECONDS):
        return {}
    return entry


def district_cache_key(country_code, city, district):
    return '|'.join(('district', normalize_country_code(country_code),
                     booking_search.normalize_label(city),
                     booking_search.normalize_label(district)))


def cached_district_id(cache_path, country_code, city, district):
    """Booking's neighbourhood id for this city district, from the disk cache."""
    entry = _cache_lookup(
        cache_path, district_cache_key(country_code, city, district))
    return str(entry.get('district_id') or '')


def remember_district_id(cache_path, country_code, city, district, district_id):
    _cache_store(cache_path,
                 district_cache_key(country_code, city, district),
                 {'district_id': str(district_id)})


def _cache_store(cache_path, key, value):
    payload = _cache_read(cache_path)
    payload[key] = dict(value, saved_at=int(time.time()))
    _cache_write(cache_path, payload)


def resolve_city_destination(session, country_code, *names, cache_path=''):
    """Resolve a city to Booking's ``dest_id`` through its content pages.

    ``names`` are the city's English and Arabic spellings; the English country
    page is tried first, the Arabic one second. A resolved city is cached in
    memory and, when ``cache_path`` is given, on disk — one unlucky page load
    must not cost the next competitor run its hotels.
    """
    country = normalize_country_code(country_code)
    wanted = [str(name or '').strip() for name in names if str(name or '').strip()]
    if not country or not wanted:
        print(f'[BOOKING DEST] cannot resolve country={country_code!r} '
              f'names={wanted!r}', flush=True)
        return {}
    key = f'{country}|{booking_search.normalize_label(wanted[0])}'
    with _LOCK:
        cached = _RESOLVED.get(key)
    if cached:
        return dict(cached)
    stored = _cache_lookup(cache_path, key)
    if stored:
        with _LOCK:
            _RESOLVED[key] = dict(stored)
        return dict(stored)
    for lang in COUNTRY_LANGS:
        country_url = country_page_url(country, lang)
        page = _fetch(session, country_url,
                      predicate=lambda html: bool(city_links(html)))
        if not page.get('html') or page.get('error'):
            print(f'[BOOKING DEST] country page failed lang={lang} '
                  f'error={page.get("error")!r}', flush=True)
            continue
        city_url = pick_city_link(page.get('html') or '', *wanted)
        if not city_url:
            print(f'[BOOKING DEST] no city link for {wanted!r} on {country_url}',
                  flush=True)
            continue
        city_page = _fetch(
            session, city_url,
            predicate=lambda html: bool(parse_destination(html)))
        destination = (parse_destination(city_page.get('html') or '')
                       if not city_page.get('error') else {})
        if not destination.get('dest_id'):
            print(f'[BOOKING DEST] no dest_id on {city_url} '
                  f'error={city_page.get("error")!r}', flush=True)
            continue
        resolved = dict(destination, city_url=city_url, country=country)
        with _LOCK:
            _RESOLVED[key] = dict(resolved)
        _cache_store(cache_path, key, resolved)
        return resolved
    return {}
