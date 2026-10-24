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

import re
import threading
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import booking_search

COUNTRY_PAGE_URL = 'https://www.booking.com/country/{country}.html?lang={lang}'
COUNTRY_LANGS = ('en-us', 'ar')
BOOKING_ORIGIN = 'https://www.booking.com'
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


def resolve_city_destination(session, country_code, *names):
    """Resolve a city to Booking's ``dest_id`` through its content pages.

    ``names`` are the city's English and Arabic spellings; the English country
    page is tried first, the Arabic one second. A resolved city is cached for
    the process so the second star class reuses it.
    """
    country = normalize_country_code(country_code)
    wanted = [str(name or '').strip() for name in names if str(name or '').strip()]
    if not country or not wanted:
        return {}
    key = (country, tuple(booking_search.normalize_label(name) for name in wanted))
    with _LOCK:
        cached = _RESOLVED.get(key)
    if cached:
        return dict(cached)
    for lang in COUNTRY_LANGS:
        page = session.fetch_html(country_page_url(country, lang))
        if not isinstance(page, dict) or page.get('error') or not page.get('html'):
            continue
        city_url = pick_city_link(page.get('html') or '', *wanted)
        if not city_url:
            continue
        city_page = session.fetch_html(city_url)
        if not isinstance(city_page, dict) or city_page.get('error'):
            continue
        destination = parse_destination(city_page.get('html') or '')
        if not destination.get('dest_id'):
            continue
        resolved = dict(destination, city_url=city_url, country=country)
        with _LOCK:
            _RESOLVED[key] = dict(resolved)
        return resolved
    return {}
