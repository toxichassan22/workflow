"""Deterministic Booking.com room-rate extraction.

The property page's room table is the only place Booking exposes a nightly
price together with the room's area. Reading it as free text lets a model pick
a breakfast-included/flexible rate or a higher room category for the same
area, which is why the same stay could be reported ~20% above the price the
owner compares against.

The owner's comparison basis is the **original nightly price before Booking's
discount**, for the cheapest base (room-only) rate that fits the requested
occupancy, before taxes. This module reads the live DOM instead:

- ``## BOOKING_RATE ##`` carries that original pre-discount price, the room
  area, the current discounted price (informational), the taxes line and the
  rate policy.
- ``select_cheapest_rate`` identifies the base rate by its current price,
  prefers a room-only rate over a breakfast-included sibling, and reports the
  base rate's original price. It never averages or builds a range across rate
  plans, and never adds taxes.
- ``parse_rate_block`` lets the market pipeline apply the block even when the
  model's own JSON picked a different figure.
"""

import os
import re

BOOKING_RATE_START = '## BOOKING_RATE ##'
BOOKING_RATE_END = '## END_BOOKING_RATE ##'
BOOKING_TABLE_ROW_SELECTOR = '#hprt-table tr[data-block-id]'


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
    return value if 1 <= value <= 2000 else None


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
    """Turn one DOM row into the fields the selector and block need."""
    raw = raw if isinstance(raw, dict) else {}
    block_id = str(raw.get('block_id') or '')
    parts = block_id.split('_')
    price = parse_number(raw.get('price_attr'))
    if price is None:
        price = parse_number(raw.get('current_text'))
    currency = (parse_currency(raw.get('current_text'))
                or parse_currency(raw.get('price_attr')) or '')
    original_price = parse_number(raw.get('original_value'))
    if original_price is None:
        original_price = parse_number(raw.get('original_text'))
    taxes, tax_included = _parse_taxes(raw)
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


def select_cheapest_rate(rows, adults=2):
    """Base room's original pre-discount nightly price for ``adults``.

    The current price identifies the cheapest base rate; a room-only rate wins
    over a breakfast-included sibling for the same room. The figure returned in
    ``price`` is that base rate's original price before Booking's discount —
    the owner's comparison basis — and taxes stay informational.
    """
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
    if not eligible:
        return None
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
    selected = _fill_room_metadata(eligible, dict(base_rows[0]))
    current_price = selected['price']
    original_price = selected.get('original_price')
    comparison_price = (original_price if original_price and original_price > 0
                        else current_price)
    taxes = selected.get('taxes')
    current_total = current_price if selected.get('tax_included') else (
        current_price + taxes if taxes is not None else None)
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


def extract_booking_rate(page, url='', adults=2):
    """Read the DOM of an already-loaded Booking property page."""
    try:
        data = page.evaluate(BOOKING_RATE_JS)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get('found'):
        return None
    rate = select_cheapest_rate(data.get('rows') or [], adults=adults)
    if not rate:
        return None
    try:
        final_url = page.url or url
    except Exception:
        final_url = url
    requested = str(url or '')
    rate['source_url'] = (requested if 'booking.com/hotel/' in requested
                          else (final_url or requested))
    rate['page_title'] = str(data.get('title') or '')
    return rate


def format_rate_block(rate):
    if not isinstance(rate, dict) or rate.get('price') is None:
        return ''
    taxes = rate.get('taxes')
    current = rate.get('current_price')
    current_total = rate.get('current_price_including_tax')
    lines = [
        BOOKING_RATE_START,
        'source_url: ' + str(rate.get('source_url') or ''),
        'room_name: ' + str(rate.get('room_name') or ''),
        'area_sqm: ' + ('' if rate.get('area_sqm') is None else f"{rate['area_sqm']:g}"),
        'adults: ' + str(rate.get('adults') if rate.get('adults') is not None else ''),
        'nightly_price_before_discount: ' + f"{rate['price']:g}",
        'current_price_after_discount: '
        + ('' if current is None else f'{current:g}'),
        'currency: ' + str(rate.get('currency') or 'SAR'),
        'taxes_and_fees_current_rate: ' + ('' if taxes is None else f'{taxes:g}'),
        'current_total_including_tax: '
        + ('' if current_total is None else f'{current_total:g}'),
        'tax_included: ' + ('true' if rate.get('tax_included') else 'false'),
        'rate_policy: ' + str(rate.get('rate_policy') or ''),
        'price_basis: original pre-discount nightly price of the cheapest base room, '
        'before taxes; the discounted current price is informational',
        BOOKING_RATE_END,
    ]
    return '\n'.join(lines)


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
    }


def with_rate_block(rate, text=''):
    """Prepend the block to page text so it survives the tool/citation caps."""
    block = format_rate_block(rate)
    if not block:
        return text or ''
    return f'{block}\n\n{text or ""}'
