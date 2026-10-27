#!/usr/bin/env python3
"""Save the whole Booking property page from the host that runs the market job.

Instead of asking the rate reader what it found, this writes the page itself —
so the markup can be read by a person afterwards:

    <out>.html        the DOM after JavaScript painted it (what the pipeline reads)
    <out>.raw.html    the same URL fetched through the browser session, no JS
    <out>.rows.json   the room rows the pipeline extracts, for comparison

It also prints a small evidence report: how many price/tax markers the page
carries and the text around each of them. A page whose markup holds a stated
tax amount while the stored row does not is an extraction problem; a page whose
markup holds one folded total is the response itself.

The dump never writes to the database or to any app state.

    PYTHONPATH=. .venv/bin/python scripts/booking_page_dump.py
    PYTHONPATH=. .venv/bin/python scripts/booking_page_dump.py --out /tmp/page.html
"""

import argparse
import json
import re
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (repo-root sys.path wiring)

import booking_rooms
import browser
import hotel_stay

DEFAULT_URL = 'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.html'
DEFAULT_OUT = 'sandbox/booking_dump/booking_page.html'

# Markers that decide which of the two price shapes the page carries.
_MARKERS = (
    'data-hotel-rounded-price',
    'data-excl-charges-raw',
    'prd-taxes-and-fees-under-price',
    'Includes taxes',
    'taxes and fees',
    'impuestos',
    'ضرائب',
)

_POS_JS = """() => {
  const picker = document.querySelector(
    '[data-testid="footer-currency-picker-trigger-desktop"]');
  return {
    title: document.title || '',
    lang: document.documentElement.getAttribute('lang') || '',
    picker: picker
      ? (picker.getAttribute('aria-label') || picker.innerText || '').trim() : '',
    rows: document.querySelectorAll('#hprt-table tr[data-block-id]').length,
  };
}"""


def tax_evidence(html, limit=3):
    """Counts and surrounding text for every price/tax marker in ``html``.

    Pure so it can be checked without a network: the dump is only useful if
    the report names what the page actually says.
    """
    text = str(html or '')
    counts = {marker: text.count(marker) for marker in _MARKERS}
    snippets = {}
    for marker in ('data-excl-charges-raw', 'data-hotel-rounded-price',
                   'Includes taxes', 'taxes and fees'):
        found = []
        start = 0
        while len(found) < limit:
            index = text.find(marker, start)
            if index < 0:
                break
            chunk = text[max(0, index - 70): index + 130]
            found.append(re.sub(r'\s+', ' ', chunk).strip())
            start = index + len(marker)
        snippets[marker] = found
    return {'bytes': len(text), 'counts': counts, 'snippets': snippets}


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument('--report-only', action='store_true',
                        help='print the evidence report, write no files')
    args = parser.parse_args()
    url = hotel_stay.with_booking_stay_params(args.url)
    out = Path(args.out)
    print(f'property: {url}')
    print(f'out: {out}')
    worker = browser.BrowserWorker(headless=True)
    try:
        worker.start()
        page = worker._page
        booking_rooms.apply_user_agent(
            page, browser.USER_AGENT, browser.ACCEPT_LANGUAGE)
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        ready = booking_rooms.wait_for_rate_rows(
            page, booking_rooms.BOOKING_TABLE_TIMEOUT_MS)
        print(f'rows ready: {ready}')
        print('page: ' + json.dumps(page.evaluate(_POS_JS), ensure_ascii=False))

        rendered = page.content()
        rows = page.evaluate(booking_rooms.BOOKING_RATE_JS)
        raw = ''
        try:
            response = page.request.get(url, timeout=60000)
            raw = response.text()
        except Exception as exc:
            print(f'raw fetch failed: {type(exc).__name__}: {exc}')

        report = tax_evidence(rendered)
        print('rendered: bytes=%d counts=%s'
              % (report['bytes'], json.dumps(report['counts'])))
        for marker, snippets in report['snippets'].items():
            for snippet in snippets:
                print(f'  [{marker}] {snippet[:190]}')
        if raw:
            raw_report = tax_evidence(raw)
            print('raw: bytes=%d counts=%s'
                  % (raw_report['bytes'], json.dumps(raw_report['counts'])))

        if args.report_only:
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding='utf-8')
        if raw:
            out.with_suffix('.raw.html').write_text(raw, encoding='utf-8')
        out.with_suffix('.rows.json').write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'wrote {out} ({out.stat().st_size} bytes)')
        return 0
    finally:
        try:
            worker.close()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
