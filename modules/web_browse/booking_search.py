"""Booking.com's own hotel discovery (search-results page).

The browse agent used to discover hotels through general web search, then hope
a property page appeared. That meant competitors could come back from
portals/fallbacks instead of Booking. This module builds a Booking search URL
and reads the property cards directly, so hotel discovery is Booking-only.

The cards are used for discovery (name, property URL, location, review). The
nightly price still comes from the property page's deterministic
``## BOOKING_RATE ##`` block — the search page's current price is context only.

A search URL must carry the destination id: a free-text ``ss`` (a district
name, or any search from the staging host) is answered with a redirect to the
homepage and ``errorc_searchstring_not_found=ss``, so a district is applied
through Booking's own neighbourhood filter (``nflt=di=<id>``) instead.
"""

from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit
import re

import booking_rooms
import hotel_stay

BOOKING_SEARCH_START = '## BOOKING_SEARCH ##'
BOOKING_SEARCH_END = '## END_BOOKING_SEARCH ##'
BOOKING_CARD_SELECTOR = '[data-testid="property-card"]'
BOOKING_SEARCH_MAX_HOTELS = 25
BOOKING_BLOCK_MAX_HOTELS = 15
SEARCH_STRING_REFUSED = 'errorc_searchstring_not_found'
_CARD_NAME_SUFFIX_RE = re.compile(
    r',?\s*(?:Property|مكان الإقامة)\s*$', re.IGNORECASE)
_DIACRITICS_RE = re.compile(r'[\u064b-\u0652\u0670\u0640]')



def is_booking_search_url(url):
    """True for Booking search-results pages (not property pages)."""
    try:
        parsed = urlsplit(str(url or '').strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in ('http', 'https'):
        return False
    host = (parsed.hostname or '').lower().rstrip('.')
    if not (host == 'booking.com' or host.endswith('.booking.com')):
        return False
    return parsed.path.lower().startswith('/searchresults')


def build_search_url(city, query='', check_in=None, check_out=None,
                     adults=2, children=0, rooms=1, currency='SAR', stars=None,
                     dest_id='', dest_type='city', district_id=''):
    """Booking search-results URL for a city, a destination id and filters.

    ``ss`` is the city text only. A free-text ``ss`` naming a district is
    refused by Booking with ``errorc_searchstring_not_found=ss`` (measured
    2026-10-24), and the same refusal hits every free-text search from the
    staging host, so the resolved ``dest_id`` is what actually runs the search.
    The district is applied as Booking's own neighbourhood filter
    (``nflt=class=N;di=<id>``), never as text.

    ``query`` overrides the free-text ``ss`` (a property-name verification
    search). Dates come from the shared stay window when omitted.
    """
    if not query:
        query = str(city or '')
    default_in, default_out = hotel_stay.booking_stay_window()
    check_in = check_in if isinstance(check_in, date) else default_in
    check_out = check_out if isinstance(check_out, date) else default_out
    params = {
        'ss': str(query or ''),
        'checkin': check_in.isoformat(),
        'checkout': check_out.isoformat(),
        'group_adults': str(adults),
        'group_children': str(children),
        'no_rooms': str(rooms),
        'selected_currency': str(currency or 'SAR'),
    }
    if dest_id not in (None, ''):
        params['dest_id'] = str(dest_id)
        params['dest_type'] = str(dest_type or 'city')
    filters = []
    if stars not in (None, ''):
        filters.append(f'class={stars}')
    if district_id not in (None, ''):
        filters.append(f'di={district_id}')
    if filters:
        params['nflt'] = ';'.join(filters)
    return 'https://www.booking.com/searchresults.html?' + urlencode(params)


def normalize_label(value):
    """Fold a Booking label or a project name for comparison.

    Arabic districts reach the app from the client (`حي الأندلس`) and from
    Booking's own filter panel (`الأندلس`), so hamza forms, ta-marbuta,
    diacritics and punctuation are folded before they are compared.
    """
    text = str(value or '').strip().casefold()
    text = _DIACRITICS_RE.sub('', text)
    for source, target in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ٱ', 'ا'),
                           ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        text = text.replace(source, target)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


def _district_name_variants(name):
    """The name without the words that only describe it (`حي …`, `… District`)."""
    normalized = normalize_label(name)
    if not normalized:
        return []
    variants = {normalized}
    tokens = normalized.split()
    while tokens and tokens[0] in ('حي', 'حيي'):
        tokens = tokens[1:]
        variants.add(' '.join(tokens))
    while tokens and tokens[-1] in ('district', 'neighbourhood',
                                    'neighborhood', 'area'):
        tokens = tokens[:-1]
        variants.add(' '.join(tokens))
    return [variant for variant in variants if len(variant) >= 3]


def match_district_facet(facets, *names):
    """The Booking neighbourhood facet matching one of the given names."""
    wanted = []
    for name in names:
        wanted.extend(_district_name_variants(name))
    if not wanted or not facets:
        return None
    for name in sorted(set(wanted), key=len, reverse=True):
        for facet in facets:
            label = normalize_label(facet_label(facet))
            if not label:
                continue
            if (label == name or label.startswith(name)
                    or name.startswith(label) or name in label):
                return facet
    return None


def facet_label(facet):
    """A facet's label without Booking's trailing property count."""
    return re.sub(r'\s*\d+\s*$', '',
                  str((facet or {}).get('label') or '')).strip()


def search_error_code(final_url):
    """Booking's own refusal code from a redirected search page, if any."""
    try:
        query = dict(parse_qsl(urlsplit(str(final_url or '')).query))
    except ValueError:
        return ''
    for key in query:
        if key.startswith('errorc_'):
            return key[len('errorc_'):]
    return ''


_FACETS_JS = """() => Array.from(
  document.querySelectorAll('[data-filters-item^="di:"]'))
  .slice(0, 60)
  .map(el => ({
    raw: el.getAttribute('data-filters-item') || '',
    label: ((el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
  }))"""

_FACET_ID_RE = re.compile(r'di[=:](\d+)')


def extract_district_facets(page):
    """Booking's neighbourhood filters (id + label) from a search page."""
    try:
        raw = page.evaluate(_FACETS_JS)
    except Exception:
        return []
    facets = []
    seen = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        match = _FACET_ID_RE.search(str(item.get('raw') or ''))
        label = str(item.get('label') or '').strip()
        if not match or not label or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        facets.append({'id': match.group(1), 'label': label})
    return facets


def wait_for_property_cards(page, timeout_ms=None):
    """Wait until at least one property card is attached."""
    try:
        page.wait_for_selector(
            BOOKING_CARD_SELECTOR,
            timeout=int(timeout_ms or booking_rooms.BOOKING_TABLE_TIMEOUT_MS))
        return True
    except Exception:
        return False


_SEARCH_JS = """() => {
  const txt = (el) => el ? ((el.innerText || el.textContent || '')
      .replace(/\\s+/g, ' ').trim()) : '';
  const cards = Array.from(document.querySelectorAll('[data-testid="property-card"]'));
  return {
    found: cards.length > 0,
    url: location.href,
    title: document.title,
    hotels: cards.slice(0, LIMIT).map((card, i) => {
      const name = (card.getAttribute('aria-label') || '')
        .replace(/,?\\s*Property\\s*$/i, '').trim()
        || txt(card.querySelector('[data-testid="title"]'));
      const link = card.querySelector('a[href*="/hotel/"]');
      return {
        index: i,
        name: name,
        url: link ? link.href : '',
        price_text: txt(card.querySelector('[data-testid="price-and-discounted-price"]')),
        review: txt(card.querySelector('[data-testid="review-score"]')),
        location: txt(card.querySelector('[data-testid="address"]')),
        text: txt(card).slice(0, 600),
      };
    })
  };
}"""


def extract_search_results(page, limit=BOOKING_SEARCH_MAX_HOTELS):
    """Read property cards from an already-loaded Booking search page."""
    try:
        data = page.evaluate(_SEARCH_JS.replace('LIMIT', str(int(limit))))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get('found'):
        return None
    hotels = []
    for item in data.get('hotels') or []:
        if not isinstance(item, dict):
            continue
        name = _CARD_NAME_SUFFIX_RE.sub(
            '', str(item.get('name') or '')).strip()
        url = str(item.get('url') or '').strip()
        if not name or not hotel_stay.is_booking_hotel_url(url):
            continue
        hotels.append({
            'name': name,
            'url': url,
            'price_text': str(item.get('price_text') or '').strip(),
            'review': str(item.get('review') or '').strip(),
            'location': str(item.get('location') or '').strip(),
            'text': str(item.get('text') or '').strip(),
        })
    if not hotels:
        return None
    return {
        'search_url': str(data.get('url') or ''),
        'title': str(data.get('title') or ''),
        'hotels': hotels,
    }


def format_search_block(data, max_hotels=BOOKING_BLOCK_MAX_HOTELS):
    """A compact block the agent can use to open property pages."""
    if not isinstance(data, dict) or not data.get('hotels'):
        return ''
    hotels = data['hotels'][:max_hotels]
    lines = [
        BOOKING_SEARCH_START,
        'search_url: ' + str(data.get('search_url') or ''),
        'title: ' + str(data.get('title') or ''),
        f'hotel_count: {len(data["hotels"])}',
    ]
    for index, hotel in enumerate(hotels, 1):
        lines.extend([
            f'[{index}] {hotel.get("name") or ""}',
            'url: ' + str(hotel.get('url') or ''),
            'price_text: ' + str(hotel.get('price_text') or ''),
            'review: ' + str(hotel.get('review') or ''),
            'location: ' + str(hotel.get('location') or ''),
            'text: ' + str(hotel.get('text') or '')[:300],
        ])
    lines.append(BOOKING_SEARCH_END)
    return '\n'.join(lines)


def with_search_block(data, text=''):
    block = format_search_block(data)
    if not block:
        return text or ''
    return f'{block}\n\n{text or ""}'
