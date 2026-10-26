#!/usr/bin/env python3
"""Show every figure Booking prints for a property's room table.

Run this on the machine that hosts the browser (the server), pointing at the
property whose price the client questions. It opens the page exactly the way
the market job does — same stay window, same user agent, same rate reader —
then prints each room row's raw DOM figures:

    price_attr      data-hotel-rounded-price (the figure the pipeline uses)
    current_text    the price the page prints
    original_text   the struck-through pre-discount price
    taxes_text      the taxes line, and whether it says «شامل»
    taxes_raw       data-excl-charges-raw — the excluded charges amount

and finally what the pipeline would store from those rows (applied range,
the pre-tax division included).

Pass ``--cookie name=value`` (repeatable) to reload the page with a cookie set,
which is how a different country view — the one a client in Saudi Arabia sees,
prices before tax with the taxes line separate — can be tested without changing
any app code:

    python scripts/booking_tax_probe.py --cookie cc1=sa

The probe never writes to the database or to any app state.
"""

import argparse
import json
import sys

import _bootstrap  # noqa: F401  (repo-root sys.path wiring)

import booking_rooms
import browser
import hotel_stay

DEFAULT_URL = ('https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.html'
               '?checkin=2026-10-27&checkout=2026-10-28'
               '&group_adults=2&group_children=0&no_rooms=1'
               '&selected_currency=SAR')

_ROW_FIELDS = ('index', 'room_name', 'price_attr', 'current_text',
               'original_text', 'original_value', 'taxes_text', 'taxes_raw')


def read_rows(page):
    """The room table as the pipeline reads it ({} when the page has none)."""
    try:
        data = page.evaluate(booking_rooms.BOOKING_RATE_JS)
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}
    return data if isinstance(data, dict) else {}


def summarize(data):
    """What the pipeline would store from these rows, taxes basis included."""
    rows = [row for row in (data.get('rows') or []) if isinstance(row, dict)]
    if not rows:
        return {'rows': 0}
    rate = booking_rooms.select_cheapest_rate(rows) or {}
    ranges = booking_rooms.room_ranges(rows) or {}
    return {
        'rows': len(rows),
        'chosen_room': str(rate.get('room_name') or ''),
        'price': rate.get('price'),
        'current_price': rate.get('current_price'),
        'original_price': rate.get('original_price'),
        'taxes': rate.get('taxes'),
        'tax_included': bool(rate.get('tax_included')),
        'applied_from': ranges.get('price_from'),
        'applied_to': ranges.get('price_to'),
        'currency': ranges.get('currency'),
    }


def print_report(label, data):
    print(f'=== {label}')
    if data.get('error'):
        print(f'  read error: {data["error"]}')
        return
    rows = [row for row in (data.get('rows') or []) if isinstance(row, dict)]
    print(f'  found={data.get("found")} rows={len(rows)} '
          f'url={str(data.get("url") or "")[:110]}')
    for row in rows[:15]:
        cells = ' '.join(
            f'{field}={row.get(field)!r}' for field in _ROW_FIELDS
            if str(row.get(field) or '').strip())
        print(f'  - {cells}')
    print('  pipeline: ' + json.dumps(summarize(data), ensure_ascii=False))


def _cookie_pairs(values):
    pairs = []
    for item in values or []:
        name, _, value = str(item).partition('=')
        if name.strip():
            pairs.append((name.strip(), value.strip()))
    return pairs


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--cookie', action='append', default=[],
                        metavar='NAME=VALUE',
                        help='set a cookie on .booking.com, then reload')
    parser.add_argument('--rows-only', action='store_true',
                        help='skip the cookie pass even when --cookie is given')
    args = parser.parse_args()
    url = hotel_stay.with_booking_stay_params(args.url)
    print(f'property: {url}')
    worker = browser.BrowserWorker(headless=True)
    try:
        worker.start()
        worker.open_url(url)
        page = worker._page
        print_report('default session', read_rows(page))
        cookies = [] if args.rows_only else _cookie_pairs(args.cookie)
        if cookies:
            try:
                worker._context.add_cookies([
                    {'name': name, 'value': value,
                     'domain': '.booking.com', 'path': '/'}
                    for name, value in cookies])
            except Exception as exc:
                print(f'cookie set failed: {type(exc).__name__}: {exc}')
                cookies = []
        if cookies:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            booking_rooms.wait_for_rate_rows(
                page, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
            names = ','.join(name for name, _value in cookies)
            print_report(f'after cookies {names}', read_rows(page))
    finally:
        try:
            worker.close()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
