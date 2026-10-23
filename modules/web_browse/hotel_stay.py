"""The Booking.com stay window every market hotel lookup shares.

Booking hides both the nightly price and the room size until a stay is
selected — the page answers «Select dates to see this property's availability
and prices» and every later row comes back with an empty price and area. The
window is part of the observation, so all properties are opened for the same
stay: two weeks out, two nights, one room, two adults, SAR.

``with_booking_stay_params`` rewrites only property pages (``/hotel/``); city,
district and search-result pages keep their URL untouched.
"""

from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STAY_LEAD_DAYS = 14
STAY_NIGHTS = 2
STAY_PARAMS = (
    'checkin', 'checkout', 'group_adults', 'group_children',
    'no_rooms', 'selected_currency',
)


def booking_stay_window(today=None):
    """(check_in, check_out) as dates — the same window for every property."""
    base = today if isinstance(today, date) else date.today()
    check_in = base + timedelta(days=STAY_LEAD_DAYS)
    return check_in, check_in + timedelta(days=STAY_NIGHTS)


def is_booking_hotel_url(url):
    """True for a Booking.com property page, the only page that carries prices."""
    try:
        parsed = urlsplit(str(url or '').strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in ('http', 'https'):
        return False
    host = (parsed.hostname or '').lower().rstrip('.')
    if not (host == 'booking.com' or host.endswith('.booking.com')):
        return False
    return parsed.path.lower().startswith('/hotel/')


def with_booking_stay_params(url, check_in=None, check_out=None):
    """Return ``url`` carrying the shared stay, or unchanged when it is not a
    Booking property page. The stay keys are replaced, never duplicated; every
    other query parameter and the fragment survive."""
    if not is_booking_hotel_url(url):
        return str(url or '')
    default_in, default_out = booking_stay_window()
    check_in = check_in if isinstance(check_in, date) else default_in
    check_out = check_out if isinstance(check_out, date) else default_out
    parsed = urlsplit(str(url))
    query = [(key, value) for key, value in parse_qsl(
        parsed.query, keep_blank_values=True) if key not in STAY_PARAMS]
    query.extend([
        ('checkin', check_in.isoformat()),
        ('checkout', check_out.isoformat()),
        ('group_adults', '2'),
        ('group_children', '0'),
        ('no_rooms', '1'),
        ('selected_currency', 'SAR'),
    ])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                       urlencode(query), parsed.fragment))
