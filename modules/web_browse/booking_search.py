"""Booking.com's own hotel discovery (search-results page).

The browse agent used to discover hotels through general web search, then hope
a property page appeared. That meant competitors could come back from
portals/fallbacks instead of Booking. This module builds a Booking search URL
and reads the property cards directly, so hotel discovery is Booking-only.

The cards are used for discovery (name, property URL, location, review). The
nightly price still comes from the property page's deterministic
``## BOOKING_RATE ##`` block — the search page's current price is context only.
"""

from datetime import date
from urllib.parse import urlencode, urlsplit
import re

import booking_rooms
import hotel_stay

BOOKING_SEARCH_START = '## BOOKING_SEARCH ##'
BOOKING_SEARCH_END = '## END_BOOKING_SEARCH ##'
BOOKING_CARD_SELECTOR = '[data-testid="property-card"]'
BOOKING_SEARCH_MAX_HOTELS = 25
BOOKING_BLOCK_MAX_HOTELS = 15
_CARD_NAME_SUFFIX_RE = re.compile(
    r',?\s*(?:Property|مكان الإقامة)\s*$', re.IGNORECASE)


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


def build_search_url(city, district='', query='', check_in=None, check_out=None,
                     adults=2, children=0, rooms=1, currency='SAR', stars=None):
    """Booking search-results URL for a city/district or a specific hotel name.

    ``query`` overrides the free-text ``ss`` value (e.g. ``"WA Hotel, Jeddah"``
    for verification). Dates come from the shared stay window when omitted.
    """
    if not query:
        query = f'{district}, {city}' if district else str(city or '')
    default_in, default_out = hotel_stay.booking_stay_window()
    check_in = check_in if isinstance(check_in, date) else default_in
    check_out = check_out if isinstance(check_out, date) else default_out
    params = {
        'ss': str(query or ''),
        'dest_type': 'city',
        'checkin': check_in.isoformat(),
        'checkout': check_out.isoformat(),
        'group_adults': str(adults),
        'group_children': str(children),
        'no_rooms': str(rooms),
        'selected_currency': str(currency or 'SAR'),
    }
    if stars not in (None, ''):
        params['nflt'] = f'class={stars}'
    return 'https://www.booking.com/searchresults.html?' + urlencode(params)


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
