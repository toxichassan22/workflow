#!/usr/bin/env python3
"""Try every client-side lever Booking might honour for its tax display.

Booking's room table either prints a room price with a separate «+X taxes and
fees» line (ex-tax, what a client in Saudi Arabia sees) or folds the taxes
into one printed total («Includes taxes and fees», what a server in Europe is
served). Which one it prints is not documented; this tool measures whether any
lever we can set from code changes it.

Run it on the host whose view matters — the deployment server — pointing at a
property, and it prints one line per variant:

    variant | pos flag | rows | printed price | taxes line | taxes_raw | stored

``taxes_raw`` (``data-excl-charges-raw``) is the field the pipeline needs: an
amount there means the row can be stored ex-tax. A variant that produces it on
a server that otherwise gets the inclusive view is the free fix.

The probe never writes to the database or to any app state.
"""

import argparse
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import _bootstrap  # noqa: F401  (repo-root sys.path wiring)

import booking_rooms
import browser
import hotel_stay

DEFAULT_URL = ('https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.html')

_PARAMS = {
    'base': {},
    'lang=en-us + USD': {'lang': 'en-us', 'selected_currency': 'USD'},
    'lang=en-gb + EUR': {'lang': 'en-gb', 'selected_currency': 'EUR'},
    'lang=ar + SAR': {'lang': 'ar', 'selected_currency': 'SAR'},
    'cc1=sa url': {'cc1': 'sa'},
    'cc1=us url': {'cc1': 'us'},
}
_COOKIES = {
    'cc1=sa cookie': {'cc1': 'sa'},
    'cc1=us cookie': {'cc1': 'us'},
    'cc1=de cookie': {'cc1': 'de'},
}

_POS_JS = """() => {
  const img = document.querySelector('img[src*="images-flags"]');
  const flag = img ? (img.getAttribute('src') || '').split('/').pop() : '';
  const picker = document.querySelector(
    '[data-testid="footer-currency-picker-trigger-desktop"]');
  const label = picker
    ? (picker.getAttribute('aria-label') || picker.innerText || '').trim() : '';
  return {flag: flag, picker: label.slice(0, 60)};
}"""


def variant_url(base, params):
    """The shared stay plus this variant's parameters, never a duplicate key.

    Appending blindly left ``selected_currency=SAR`` in front of the variant's
    ``selected_currency=USD``, so the currency variants were measured in riyals
    while their label claimed dollars — a matrix that cannot see the lever it
    claims to test. A variant's key replaces the stay's key instead.
    """
    url = hotel_stay.with_booking_stay_params(base)
    if not params:
        return url
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(
        parsed.query, keep_blank_values=True) if key not in params]
    query.extend((key, str(value)) for key, value in params.items())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                       urlencode(query), parsed.fragment))


def read_state(page, url):
    try:
        pos = page.evaluate(_POS_JS)
    except Exception:
        pos = {}
    try:
        data = page.evaluate(booking_rooms.BOOKING_RATE_JS)
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}', 'pos': pos}
    rows = [row for row in (data.get('rows') or []) if isinstance(row, dict)]
    rate = booking_rooms.select_cheapest_rate(rows) or {}
    first = rows[0] if rows else {}
    return {
        'pos': pos,
        'rows': len(rows),
        'price_attr': first.get('price_attr'),
        'current_text': first.get('current_text'),
        'taxes_text': first.get('taxes_text'),
        'taxes_raw': first.get('taxes_raw'),
        'stored': rate.get('price'),
        'tax_included': bool(rate.get('tax_included')),
    }


def print_row(label, state):
    pos = state.get('pos') or {}
    cells = [
        label,
        'flag=' + str(pos.get('flag') or ''),
        'picker=' + repr(str(pos.get('picker') or '')[:24]),
        'rows=' + str(state.get('rows')),
        'current=' + repr(str(state.get('current_text') or '')[:20]),
        'taxes=' + repr(str(state.get('taxes_text') or '')[:30]),
        'taxes_raw=' + repr(str(state.get('taxes_raw') or '')),
        'stored=' + str(state.get('stored')),
        'included=' + str(state.get('tax_included')),
    ]
    if state.get('error'):
        cells.append('error=' + state['error'][:60])
    print(' | '.join(cells), flush=True)


def run_variant(worker, base, label, params=None, cookies=None):
    page = worker._page
    context = worker._context
    try:
        context.clear_cookies()
    except Exception:
        pass
    if cookies:
        try:
            context.add_cookies([
                {'name': name, 'value': value, 'domain': '.booking.com',
                 'path': '/'} for name, value in cookies.items()])
        except Exception as exc:
            print(f'{label} | cookie set failed: {type(exc).__name__}: {exc}')
    url = variant_url(base, params)
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        booking_rooms.wait_for_rate_rows(
            page, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
    except Exception as exc:
        print(f'{label} | goto failed: {type(exc).__name__}: {exc}', flush=True)
        return
    print_row(label, read_state(page, url))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--only', default='', help='substring filter on labels')
    args = parser.parse_args()
    base = args.url
    if not hotel_stay.is_booking_hotel_url(base):
        print(f'not a Booking property page: {base}')
        return 2
    print(f'property: {variant_url(base, {})}')
    worker = browser.BrowserWorker(headless=True)
    try:
        worker.start()
        booking_rooms.apply_user_agent(
            worker._page, browser.USER_AGENT, browser.ACCEPT_LANGUAGE)
        for label, params in _PARAMS.items():
            if args.only and args.only not in label:
                continue
            run_variant(worker, base, label, params=params)
        for label, cookies in _COOKIES.items():
            if args.only and args.only not in label:
                continue
            run_variant(worker, base, label, cookies=cookies)
    finally:
        try:
            worker.close()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
