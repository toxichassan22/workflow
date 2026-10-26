"""Deterministic Booking hotel catalogue for name-based competitor fill.

Booking's city page is a curated subset; its category pages expose a wider
inventory. This module reads those public pages and returns canonical hotel
links. It never calls a model or a search engine.
"""

import re
import time
from urllib.parse import urljoin, urlsplit

import booking_destination

BOOKING_ORIGIN = 'https://www.booking.com'
CATEGORY_PAGES = ('aparthotels', 'budget', 'hostels', 'luxury', 'resorts')
_HOTEL_PATH_RE = re.compile(r'^/hotel/([a-z]{2})/([^/]+?)\.html$', re.I)
_LANGUAGE_SUFFIX_RE = re.compile(r'(?:\.[a-z-]{2,})+$', re.I)
_CITY_PATH_RE = re.compile(r'^/city/([a-z]{2})/([^/]+)$', re.I)


def canonical_hotel_url(href):
    """Return the language-independent Booking property URL, or empty."""
    absolute = urljoin(BOOKING_ORIGIN, str(href or '').strip())
    parts = urlsplit(absolute)
    host = (parts.hostname or '').lower().rstrip('.')
    if not (host == 'booking.com' or host.endswith('.booking.com')):
        return ''
    match = _HOTEL_PATH_RE.match(parts.path)
    if not match:
        return ''
    country = match.group(1).lower()
    slug = _LANGUAGE_SUFFIX_RE.sub('', match.group(2))
    if not slug:
        return ''
    return f'{BOOKING_ORIGIN}/hotel/{country}/{slug}.html'


def category_page_urls(city_url):
    """The catalogue pages that sit beside a Booking city page."""
    parts = urlsplit(str(city_url or '').strip())
    match = _CITY_PATH_RE.match(parts.path)
    if not match:
        return []
    city_path = f'{match.group(1).lower()}/{match.group(2)}'
    return [f'{BOOKING_ORIGIN}/{category}/city/{city_path}'
            for category in CATEGORY_PAGES]


def _merge_names(*values):
    """Keep every language/spelling of one property, without duplicates."""
    aliases = []
    for value in values:
        for part in str(value or '').split('|'):
            part = ' '.join(part.split())
            if not part or any(part == alias or part in alias
                               for alias in aliases):
                continue
            aliases = [alias for alias in aliases if alias not in part]
            aliases.append(part)
    return ' | '.join(aliases)


def hotel_entries_from_html(html):
    """Every `/hotel/` anchor on a page, deduplicated by canonical URL."""
    entries = {}
    for anchor in booking_destination.anchors(html):
        url = canonical_hotel_url(anchor.get('href'))
        if not url:
            continue
        name = ' '.join(str(anchor.get('text') or '').split())
        current = entries.get(url)
        entries[url] = {
            'name': _merge_names((current or {}).get('name'), name),
            'url': url,
        }
    return [entries[url] for url in sorted(entries)]


def fetch_city_catalog(session, city_url, deadline=None, log=None):
    """Read the city page and its category pages into one hotel catalogue."""
    urls = []
    if city_url:
        urls.append(str(city_url))
    urls.extend(category_page_urls(city_url))
    entries = {}
    pages = 0
    for url in dict.fromkeys(urls):
        if deadline is not None and time.time() > deadline:
            if log:
                log('booking catalogue stopped at deadline')
            break
        requested_path = urlsplit(url).path
        expected_prefix = (requested_path.split('/city/')[0] + '/city/'
                           if '/city/' in requested_path else requested_path)
        page = {}
        for attempt in range(2):
            page = session.fetch_html(url, timeout=45)
            page = page if isinstance(page, dict) else {}
            final_path = urlsplit(str(page.get('final_url') or '')).path
            if (page.get('html') and not page.get('error')
                    and (not final_path
                         or final_path.startswith(expected_prefix))):
                break
            if attempt == 0:
                time.sleep(1)
        final_url = str(page.get('final_url') or '')
        if page.get('error') or not page.get('html'):
            if log:
                log(f'booking catalogue page skipped url={url[:160]!r} '
                    f'error={page.get("error")!r}')
            continue
        final_path = urlsplit(final_url).path
        if final_path and not final_path.startswith(expected_prefix):
            if log:
                log(f'booking catalogue page skipped url={url[:160]!r} '
                    f'final={final_url[:160]!r} reason=redirect')
            continue
        pages += 1
        page_entries = hotel_entries_from_html(page.get('html') or '')
        if log:
            log(f'booking catalogue page url={url[:160]!r} '
                f'final={final_url[:160]!r} links={len(page_entries)}')
        for entry in page_entries:
            current = entries.get(entry['url'])
            if current is None or len(entry['name']) > len(current['name']):
                entries[entry['url']] = entry
    result = [entries[url] for url in sorted(entries)]
    if log:
        log(f'booking catalogue city_url={city_url!r} pages={pages} '
            f'links={len(result)}')
    return result


def merge_entries(*catalogs):
    """Merge catalogue passes by canonical URL, keeping every name alias."""
    entries = {}
    for catalog in catalogs:
        for entry in catalog or []:
            url = str((entry or {}).get('url') or '')
            if not url:
                continue
            current = entries.get(url) or {}
            entries[url] = {
                'name': _merge_names(current.get('name'), entry.get('name')),
                'url': url,
            }
    return [entries[url] for url in sorted(entries)]
