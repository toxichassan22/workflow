"""Deterministic Booking.com room-rate extraction.

The property page's room table is the only place Booking exposes a nightly
price together with the room's area. Reading it as free text lets a model pick
a breakfast-included/flexible rate or a higher room category for the same
area, which is why the same stay could be reported ~20% above the price the
owner compares against.

The owner's comparison basis is the **original pre-discount room price** for
the stay, pre-tax. Booking prints a taxes line beside the room price; in the
Saudi view that line is charged on top of the printed figure, while a session
outside Saudi Arabia is served prices with the property's taxes already folded
in (the line reads «شامل الضرائب والرسوم»). The table carries the pre-discount
figure alone, with the folded taxes taken back out and the discounted current
price kept as an informational value. This module reads the live DOM instead
of asking a model:

- ``## BOOKING_RATE ##`` carries that original price, the room area, the
  current discounted price (informational), the taxes line and the rate policy.
- ``select_cheapest_rate`` identifies the cheapest base rate for the requested
  occupancy and reports its original price.
- ``room_ranges`` spans every room row and returns the original pre-discount
  price at both ends, rounded to whole riyals.
- ``parse_rate_block`` lets the market pipeline apply the block even when the
  model's own JSON picked a different figure.
"""

import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

BOOKING_RATE_START = '## BOOKING_RATE ##'
BOOKING_RATE_END = '## END_BOOKING_RATE ##'
BOOKING_TABLE_ROW_SELECTOR = '#hprt-table tr[data-block-id]'
# The currency every Booking page is opened with (hotel_stay.STAY_PARAMS);
# data-hotel-rounded-price is rendered in it regardless of the locale display.
SELECTED_CURRENCY = 'SAR'
# A session outside Saudi Arabia gets the room table with the property's own
# taxes already folded in — the taxes line reads «شامل الضرائب والرسوم» — and
# that folded amount is the Saudi hotel stack: 15% VAT plus the 5% municipality
# fee, both levied on the net, so the displayed figure is the pre-tax price
# times 1.2075. The Saudi view prints the same room pre-tax with a separate
# taxes line. Verified against the owner's own screen on one property: the
# table's 622-1570 maps to 515-1300, both ends off by this exact factor.
KSA_HOTEL_TAX_FACTOR = 1.2075


def _table_timeout_ms():
    try:
        return max(5000, int(
            os.environ.get('BOOKING_TABLE_TIMEOUT_MS') or 60000))
    except (TypeError, ValueError):
        return 60000


BOOKING_TABLE_TIMEOUT_MS = _table_timeout_ms()

BOOKING_RATE_JS = """() => {
  const table = document.querySelector('#hprt-table');
  if (!table) return {found: false, rows: []};
  const txt = (el) => el ? ((el.innerText || el.textContent || '')
      .replace(/\\s+/g, ' ').trim()) : '';
  const rows = Array.from(table.querySelectorAll('tr[data-block-id]'))
    .map((tr, i) => {
      const current = tr.querySelector('.bui-price-display__value');
      const original = tr.querySelector('.bui-price-display__original');
      const taxes = tr.querySelector('.prd-taxes-and-fees-under-price');
      const link = tr.querySelector('a.hprt-roomtype-link');
      const name = tr.querySelector('.hprt-roomtype-name');
      const area = tr.querySelector('[data-name-en="room size"]');
      const occupancy = tr.querySelector('.c-occupancy-icons');
      return {
        index: i,
        block_id: tr.getAttribute('data-block-id') || '',
        price_attr: tr.getAttribute('data-hotel-rounded-price') || '',
        current_text: txt(current),
        original_text: txt(original),
        original_value: original
          ? (original.getAttribute('data-strikethrough-value') || '') : '',
        taxes_text: txt(taxes),
        taxes_raw: taxes
          ? (taxes.getAttribute('data-excl-charges-raw') || '') : '',
        room_name: txt(name) || txt(link),
        room_id: link ? (link.getAttribute('data-room-id') || '') : '',
        area_text: txt(area),
        occupancy_text: txt(occupancy),
        row_text: txt(tr).slice(0, 3000),
      };
    });
  return {found: true, rows: rows, url: location.href, title: document.title};
}"""

_ARABIC_DIGITS = str.maketrans(
    '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

_CURRENCY_WORDS = (
    ('US$', 'USD'), ('USD', 'USD'), ('دولار', 'USD'),
    ('SAR', 'SAR'), ('ر.س', 'SAR'), ('ر س', 'SAR'), ('ريال', 'SAR'), ('SR', 'SAR'),
    ('EGP', 'EGP'), ('ج.م', 'EGP'), ('جنيه', 'EGP'),
    ('EUR', 'EUR'), ('€', 'EUR'), ('يورو', 'EUR'),
    ('GBP', 'GBP'), ('£', 'GBP'),
)

_NUMBER_RE = re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?')
_AREA_RE = re.compile(
    r'([0-9]+(?:[.,][0-9]+)?)\s*(?:m²|m2|sqm|sq\.?\s?m|م²|م2|متر)',
    re.IGNORECASE)
_OCCUPANCY_RE = re.compile(
    r'(?:max\.?\s*people|guests?|الضيوف|الأشخاص|اشخاص)[^0-9]{0,24}([0-9٠-٩]+)',
    re.IGNORECASE)
_ROOM_AREA_SUFFIX_RE = re.compile(
    r'\s*\d+(?:[.,]\d+)?\s*(?:m²|m2|sqm|sq\.?\s?m|م²|م2|متر).*$',
    re.IGNORECASE)
_BREAKFAST_INCLUDED_RE = re.compile(
    r'breakfast\s+included|breakfast\s+is\s+included|إفطار\s+مشمول|الفطور\s+مشمول|شامل\s+الإفطار',
    re.IGNORECASE)
_BREAKFAST_RE = re.compile(r'breakfast|إفطار|فطور', re.IGNORECASE)
_FREE_CANCEL_RE = re.compile(r'free\s+cancellation|إلغاء\s+مجاني', re.IGNORECASE)
_TAX_INCLUDED_RE = re.compile(r'includ|شامل|ضمن', re.IGNORECASE)


def parse_number(value):
    """First numeric value in ``value``; commas and Arabic digits handled."""
    if value is None:
        return None
    text = str(value).translate(_ARABIC_DIGITS)
    match = _NUMBER_RE.search(text.replace('\u00a0', ' '))
    if not match:
        return None
    try:
        return float(match.group(0).replace(',', ''))
    except (TypeError, ValueError):
        return None


def parse_currency(text):
    folded = str(text or '').casefold()
    for word, code in _CURRENCY_WORDS:
        if word.casefold() in folded:
            return code
    return ''


def parse_area(text):
    match = _AREA_RE.search(str(text or '').translate(_ARABIC_DIGITS))
    if not match:
        return None
    try:
        value = float(match.group(1).replace(',', ''))
    except (TypeError, ValueError):
        return None
    # A hotel room is never 4–5 m²; a bare occupancy/room count next to a
    # stray unit in the row text used to be stored as the room area.
    return value if 8 <= value <= 2000 else None


_STARS_JS = """() => {
  const text = (el) => el ? ((el.innerText || el.textContent || '')
      .replace(/\\s+/g, ' ').trim()) : '';
  const out = [];
  document.querySelectorAll('[data-testid="rating-stars"], '
      + '[data-testid="rating-squares"]').forEach((el) => {
    out.push(el.getAttribute('aria-label') || '');
    out.push(el.getAttribute('class') || '');
    out.push(text(el));
  });
  // The class badge has moved between containers across releases, but the
  // sentence it announces is the same one, so every labelled element that
  // names a count out of five contributes its label.
  document.querySelectorAll('[aria-label]').forEach((el) => {
    const label = el.getAttribute('aria-label') || '';
    if (/من\\s*أصل|out of/i.test(label)) out.push(label);
  });
  const header = document.querySelector('h2.pp-header__title')
    || document.querySelector('[data-testid="property-name"]')
    || document.querySelector('h1');
  out.push(text(header));
  out.push(document.title || '');
  return out.join(' | ').slice(0, 2500);
}"""

# Every pattern needs the word that makes the digit a star class, so a review
# score, a distance or a year in the same header text is never read as one.
_STAR_PATTERNS = (
    re.compile(r'([1-5])\s*(?:من\s*أصل|out\s*of)\s*5'),
    re.compile(r'([1-5])\s*(?:نجوم|نجمه|نجمة)'),
    re.compile(r'([1-5])\s*-?\s*stars?\b'),
    re.compile(r'\b(?:stars?|rating)\b[^\d|]{0,10}([1-5])\b'),
)


def _read_stars(page):
    """(stars, raw) — the property's own star class and the text that says so.

    The header rating is the usual source, but Booking drops the stars widget
    on some property pages while the header still names the class («فندق 4
    نجوم»), so the header and page title are read beside it. The raw text rides
    out with a zero so a missing class can be told from a missed read.
    """
    try:
        raw = page.evaluate(_STARS_JS)
    except Exception:
        return 0, ''
    text = str(raw or '').translate(_ARABIC_DIGITS)
    for pattern in _STAR_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1)), text
    return 0, text


def extract_hotel_stars(page):
    """The property's own star class, 0 when its page states none."""
    return _read_stars(page)[0]


def whole_riyal(value):
    """Round a positive money amount half-up to the whole riyal Booking shows."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    try:
        return float(number.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def _parse_taxes(raw):
    text = str(raw.get('taxes_text') or '').strip()
    amount = parse_number(text)
    if amount is None:
        amount = parse_number(raw.get('taxes_raw'))
    return amount, bool(_TAX_INCLUDED_RE.search(text)) and not text.startswith('+')


def _block_occupancy(block_id):
    parts = str(block_id or '').split('_')
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return None


def normalize_rate_row(raw):
    """Turn one DOM row into the fields the selector and block need.

    ``data-hotel-rounded-price`` is in the requested currency, while the
    visible original/taxes figure and ``data-strikethrough-value`` render in
    the browser's local currency (measured: 535 SAR beside 7,883 EGP on the
    same row). Mixing them labelled a local-currency amount as SAR, and the
    market pipeline then converted it with a guessed FX rate — a 629 SAR room
    reached the table as 760. The row's own two current figures give the
    exact ratio, so the original and the taxes are expressed in the same
    currency as the price without any external rate.

    The ratio is a currency conversion only. When the visible amount already
    carries the requested currency, the original and the taxes are taken
    literally: applying the current/original difference as a ratio multiplied
    a discounted room's original 340 by 340/289 and turned it into 400.
    """
    raw = raw if isinstance(raw, dict) else {}
    block_id = str(raw.get('block_id') or '')
    parts = block_id.split('_')
    price_attr = parse_number(raw.get('price_attr'))
    visible_current = parse_number(raw.get('current_text'))
    price = price_attr if price_attr is not None else visible_current
    currency = SELECTED_CURRENCY if price_attr is not None and str(
        raw.get('price_attr') or '').strip() else ''
    if not currency:
        currency = (parse_currency(raw.get('current_text'))
                    or parse_currency(raw.get('price_attr')) or '')
    visible_currency = parse_currency(raw.get('current_text'))
    scale = 1.0
    if (price_attr and visible_current and price_attr > 0
            and visible_current > 0 and visible_currency
            and visible_currency != SELECTED_CURRENCY):
        scale = price_attr / visible_current
    original_price = parse_number(raw.get('original_text'))
    if original_price is None:
        original_price = parse_number(raw.get('original_value'))
    taxes, tax_included = _parse_taxes(raw)
    if abs(scale - 1.0) > 0.001:
        if original_price:
            original_price = round(original_price * scale, 1)
        if taxes:
            taxes = round(taxes * scale, 1)
    if tax_included:
        # This session's view already carries the property's taxes in the
        # figure it prints; the owner's comparison is the pre-tax one, so the
        # folded taxes come back out here.
        if price is not None and price > 0:
            price = round(price / KSA_HOTEL_TAX_FACTOR, 4)
        if original_price:
            original_price = round(original_price / KSA_HOTEL_TAX_FACTOR, 4)
        taxes = 0
    row_text = str(raw.get('row_text') or '')
    occupancy_text = str(raw.get('occupancy_text') or '')
    adults = _block_occupancy(block_id)
    if adults is None:
        match = _OCCUPANCY_RE.search((occupancy_text + ' ' + row_text).translate(_ARABIC_DIGITS))
        if match:
            adults = int(match.group(1))
    area = parse_area(raw.get('area_text'))
    if area is None:
        area = parse_area(row_text)
    room_name = _ROOM_AREA_SUFFIX_RE.sub(
        '', str(raw.get('room_name') or '')).strip(' •-')
    return {
        'index': raw.get('index'),
        'block_id': block_id,
        'room_id': str(raw.get('room_id') or (parts[0] if parts else '')),
        'room_name': room_name,
        'area_sqm': area,
        'adults': adults,
        'price': price,
        'currency': currency or 'SAR',
        'original_price': original_price,
        'taxes': taxes,
        'tax_included': tax_included,
        'breakfast_included': bool(_BREAKFAST_INCLUDED_RE.search(row_text)),
        'breakfast': bool(_BREAKFAST_RE.search(row_text)),
        'free_cancellation': bool(_FREE_CANCEL_RE.search(row_text)),
        'row_text': row_text,
    }


def _fill_room_metadata(rows, selected):
    """Rate rows after a room header omit its name and area; borrow them."""
    room_id = selected.get('room_id') or ''
    if selected.get('room_name') and selected.get('area_sqm'):
        return selected
    for row in rows:
        if row.get('room_id') != room_id:
            continue
        if not selected.get('room_name') and row.get('room_name'):
            selected['room_name'] = row['room_name']
        if not selected.get('area_sqm') and row.get('area_sqm'):
            selected['area_sqm'] = row['area_sqm']
        if selected.get('room_name') and selected.get('area_sqm'):
            break
    return selected


def _base_rows(rows, adults=2):
    """One base (room-only, cheapest) row per room type for the occupancy."""
    normalized = [normalize_rate_row(row) for row in rows or []
                  if isinstance(row, dict)]
    eligible = []
    for row in normalized:
        if row.get('price') is None or row['price'] <= 0:
            continue
        if row.get('adults') is not None:
            if row['adults'] != adults:
                continue
        eligible.append(row)
    by_room = {}
    for row in eligible:
        by_room.setdefault(row.get('room_id') or row.get('block_id') or '', []).append(row)
    base_rows = []
    for room_rows in by_room.values():
        non_breakfast = [row for row in room_rows
                         if not row.get('breakfast_included')]
        pool = non_breakfast or room_rows
        base_rows.append(min(pool, key=lambda row: (
            row['price'], row.get('index') if row.get('index') is not None else 0)))
    base_rows.sort(key=lambda row: (
        row['price'], row.get('index') if row.get('index') is not None else 0))
    return normalized, eligible, base_rows


def room_total(row):
    """One room's original pre-discount price in riyals, taxes excluded."""
    base = row.get('original_price')
    if base is None or base <= 0:
        base = row.get('price')
    if base is None or base <= 0:
        return None
    return whole_riyal(base)


def room_ranges(rows):
    """Cheapest-to-priciest original pre-discount room price and room area.

    Both ends come from **every** room on the page — suites and family rooms
    included, whatever occupancy their rate is sold for (owner decision
    2026-10-24), so the range matches the room table a client sees. The figure
    is the row's original pre-discount price alone — 340 reads 340 — never the
    discounted current price and never the row's taxes line (owner decision
    2026-10-26). A row after a room header may omit its area, so
    the area is borrowed from another row of the same room.
    """
    normalized = [normalize_rate_row(row) for row in rows or []
                  if isinstance(row, dict)]
    priced = [row for row in normalized
              if row.get('price') is not None and row['price'] > 0]
    if not priced:
        return {}
    areas_by_room = {}
    for row in normalized:
        if row.get('area_sqm'):
            areas_by_room.setdefault(
                row.get('room_id') or row.get('block_id') or '',
                row['area_sqm'])
    prices = []
    areas = []
    rooms = set()
    for row in priced:
        room_key = row.get('room_id') or row.get('block_id') or ''
        rooms.add(room_key)
        prices.append(room_total(row))
        area = row.get('area_sqm') or areas_by_room.get(room_key)
        if area:
            areas.append(area)
    prices = [price for price in prices if price is not None]
    if not prices:
        return {}
    return {
        'price_from': min(prices),
        'price_to': max(prices),
        'area_from': min(areas) if areas else None,
        'area_to': max(areas) if areas else None,
        'room_count': len(rooms),
        'currency': priced[0].get('currency') or SELECTED_CURRENCY,
    }


def select_cheapest_rate(rows, adults=2):
    """Base room's original pre-discount price for ``adults``.

    The current price identifies the cheapest base rate; a room-only rate wins
    over a breakfast-included sibling for the same room. The figure returned in
    ``price`` is that base rate's original price before Booking's discount;
    ``taxes`` rides beside it as an informational value only — the room range
    never adds it.
    """
    normalized, eligible, base_rows = _base_rows(rows, adults=adults)
    if not eligible or not base_rows:
        return None
    selected = _fill_room_metadata(eligible, dict(base_rows[0]))
    current_price = selected['price']
    original_price = selected.get('original_price')
    comparison_price = (original_price if original_price and original_price > 0
                        else current_price)
    taxes = selected.get('taxes')
    if selected.get('tax_included'):
        # current_price is already the pre-tax figure; what the property
        # charges is that figure with the view's folded taxes back on top.
        current_total = round(current_price * KSA_HOTEL_TAX_FACTOR, 4)
    else:
        current_total = (current_price + taxes
                         if taxes is not None else None)
    policy = []
    if selected.get('breakfast_included'):
        policy.append('breakfast included')
    elif selected.get('breakfast'):
        policy.append('room only; breakfast optional')
    else:
        policy.append('room only')
    if selected.get('free_cancellation'):
        policy.append('free cancellation')
    selected.update({
        'price': comparison_price,
        'current_price': current_price,
        'current_price_including_tax': current_total,
        'original_price': original_price or comparison_price,
        'taxes': taxes,
        'rate_policy': '; '.join(policy),
        'eligible_rows': len(eligible),
        'row_count': len(normalized),
    })
    return selected


def apply_user_agent(page, user_agent, accept_language, platform='Win32'):
    """Send a normal desktop UA before a Booking navigation.

    Booking answers a ``HeadlessChrome/…`` UA with the SEO property page: the
    stay dates are stripped and no price or room size exists. The CDP override
    keeps the live room table. Returns an error string, or '' on success.
    """
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send('Emulation.setUserAgentOverride', {
            'userAgent': str(user_agent or ''),
            'acceptLanguage': str(accept_language or ''),
            'platform': platform,
        })
        return ''
    except Exception as exc:
        return str(exc) or exc.__class__.__name__


def wait_for_rate_rows(page, timeout_ms=None):
    """Wait until the availability table has at least one real rate row."""
    try:
        page.wait_for_selector(
            BOOKING_TABLE_ROW_SELECTOR,
            timeout=int(timeout_ms or BOOKING_TABLE_TIMEOUT_MS))
        return True
    except Exception:
        return False


def wait_and_extract(page, url='', adults=2, retries=5, delay_ms=1000):
    """Extract the rate, retrying while the rows/prices are still painting."""
    for _ in range(max(1, int(retries or 1))):
        rate = extract_booking_rate(page, url, adults=adults)
        if rate:
            return rate
        try:
            page.wait_for_timeout(delay_ms)
        except Exception:
            break
    return None


def _print_rate_audit(rate, rows, url='', stars_raw=''):
    """One audit line per property page, naming the DOM field behind each figure.

    A table price has to be traceable to the field it came from: the chosen
    row's own raw texts (rounded-price attribute, visible current, visible
    original, taxes) sit beside the values this module applied. A page that
    states no star class prints the text it was read from instead.
    """
    block = str((rate or {}).get('block_id') or '')
    raw = next((row for row in rows or []
                if isinstance(row, dict)
                and str(row.get('block_id') or '') == block), {})
    parts = [
        '[BOOKING RATE] url=' + str(url or rate.get('source_url') or '')[:120],
        'rows=' + str(len(rows or [])),
        'chosen_room=' + repr(str(raw.get('room_name') or '')[:40]),
        'attr=' + repr(str(raw.get('price_attr') or '')),
        'current_text=' + repr(str(raw.get('current_text') or '')[:40]),
        'original_text=' + repr(str(raw.get('original_text') or '')[:40]),
        'taxes_text=' + repr(str(raw.get('taxes_text') or '')[:40]),
        'applied=' + str(rate.get('price_from')) + '-' + str(rate.get('price_to')),
        'price=' + str(rate.get('price')),
        'current=' + str(rate.get('current_price')),
        'tax_included=' + str(bool(rate.get('tax_included'))),
        'stars=' + str(rate.get('hotel_stars') or 0),
    ]
    if stars_raw:
        parts.append('stars_src=' + repr(str(stars_raw)[:160]))
    print(' '.join(parts), flush=True)


def extract_booking_rate(page, url='', adults=2):
    """Read the DOM of an already-loaded Booking property page."""
    try:
        data = page.evaluate(BOOKING_RATE_JS)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get('found'):
        return None
    rows = data.get('rows') or []
    rate = select_cheapest_rate(rows, adults=adults)
    if not rate:
        return None
    rate.update(room_ranges(rows))
    try:
        final_url = page.url or url
    except Exception:
        final_url = url
    requested = str(url or '')
    rate['source_url'] = (requested if 'booking.com/hotel/' in requested
                          else (final_url or requested))
    rate['page_title'] = str(data.get('title') or '')
    stars, stars_raw = _read_stars(page)
    if stars:
        rate['hotel_stars'] = stars
    _print_rate_audit(rate, rows, rate.get('source_url'),
                      stars_raw='' if stars else stars_raw)
    return rate


def format_rate_block(rate):
    if not isinstance(rate, dict) or rate.get('price') is None:
        return ''
    taxes = rate.get('taxes')
    current = rate.get('current_price')
    current_total = rate.get('current_price_including_tax')
    price_from = rate.get('price_from')
    price_to = rate.get('price_to')
    if price_from is None and price_to is None:
        room_only = rate.get('price')
        if room_only is not None:
            price_from = price_to = whole_riyal(room_only)
    lines = [
        BOOKING_RATE_START,
        'source_url: ' + str(rate.get('source_url') or ''),
        'room_name: ' + str(rate.get('room_name') or ''),
        'area_sqm: ' + ('' if rate.get('area_sqm') is None else f"{rate['area_sqm']:g}"),
        'adults: ' + str(rate.get('adults') if rate.get('adults') is not None else ''),
        'price_before_discount: ' + f"{rate['price']:g}",
        'current_price_after_discount: '
        + ('' if current is None else f'{current:g}'),
        'currency: ' + str(rate.get('currency') or 'SAR'),
        'taxes_and_fees_current_rate: ' + ('' if taxes is None else f'{taxes:g}'),
        'current_total_including_tax: '
        + ('' if current_total is None else f'{current_total:g}'),
        'tax_included: ' + ('true' if rate.get('tax_included') else 'false'),
        'tax_factor_removed: '
        + (f'{KSA_HOTEL_TAX_FACTOR:g}' if rate.get('tax_included') else ''),
        'rate_policy: ' + str(rate.get('rate_policy') or ''),
        'price_range_before_discount: '
        + _range_text(price_from, price_to),
        'area_range_sqm: '
        + _range_text(rate.get('area_from'), rate.get('area_to')),
        'room_type_count: ' + str(rate.get('room_count') or ''),
        'price_basis: original pre-discount room price for the stay, pre-tax, '
        'rounded to whole riyals; a view that folds the property\'s taxes into '
        'the figure it prints has that factor removed, and the discounted '
        'current price stays informational',
        BOOKING_RATE_END,
    ]
    return '\n'.join(lines)


def _range_text(low, high):
    if low is None and high is None:
        return ''
    if low is None or high is None or low == high:
        return f'{low if low is not None else high:g}'
    return f'{low:g} - {high:g}'


_BLOCK_RE = re.compile(
    re.escape(BOOKING_RATE_START) + r'(.*?)' + re.escape(BOOKING_RATE_END),
    re.DOTALL)


def parse_rate_block(text):
    """Read a ``## BOOKING_RATE ##`` block out of page/tool text."""
    match = _BLOCK_RE.search(str(text or ''))
    if not match:
        return None
    data = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(':')
        if not sep:
            continue
        data[key.strip()] = value.strip()
    price = parse_number(data.get('price_before_discount'))
    if price is None:
        # Existing stored blocks from the short-lived nightly-basis build.
        price = parse_number(data.get('nightly_price_before_discount'))
    current = parse_number(data.get('current_price_after_discount'))
    if price is None:
        price = current
    if price is None:
        return None
    area = parse_number(data.get('area_sqm'))
    taxes = parse_number(data.get('taxes_and_fees_current_rate'))
    total = parse_number(data.get('current_total_including_tax'))
    adults = parse_number(data.get('adults'))
    price_from, price_to = _parse_range(
        data.get('price_range_before_discount'))
    if price_from is None and price_to is None:
        # Blocks written before the taxes-excluded basis carry the old
        # tax-inclusive range key.
        price_from, price_to = _parse_range(
            data.get('price_range_original_plus_taxes'))
    if price_from is None and price_to is None:
        price_from, price_to = _parse_range(data.get('price_range_current'))
    if price_from is None and price_to is None:
        price_from = price_to = whole_riyal(price)
    area_from, area_to = _parse_range(data.get('area_range_sqm'))
    rooms = parse_number(data.get('room_type_count'))
    return {
        'price': price,
        'current_price': current,
        'original_price': price,
        'currency': data.get('currency') or 'SAR',
        'area_sqm': area,
        'taxes': taxes,
        'current_price_including_tax': total,
        'adults': int(adults) if adults is not None else None,
        'tax_included': str(data.get('tax_included') or '').lower() == 'true',
        'room_name': data.get('room_name') or '',
        'rate_policy': data.get('rate_policy') or '',
        'source_url': data.get('source_url') or '',
        'price_from': price_from,
        'price_to': price_to,
        'area_from': area_from,
        'area_to': area_to,
        'room_count': int(rooms) if rooms is not None else None,
    }


def _parse_range(value):
    text = str(value or '')
    if not text:
        return None, None
    parts = re.split(r'\s*-\s*', text)
    low = parse_number(parts[0])
    high = parse_number(parts[1]) if len(parts) > 1 else low
    return low, high


def with_rate_block(rate, text=''):
    """Prepend the block to page text so it survives the tool/citation caps."""
    block = format_rate_block(rate)
    if not block:
        return text or ''
    return f'{block}\n\n{text or ""}'
