#!/usr/bin/env python3
"""Probe Booking.com from a real Chrome over CDP.

Run this on the machine that will host the browser (a cloud VM, a spare PC, or
a machine with a residential proxy). It launches Chrome with a dedicated
profile, attaches over CDP, opens a Booking hotel page with dates, and prints
a verdict:

  ok          normal property page; date/price/area signals present
  bot_page    Booking served the b_bot page (no date picker / no prices)
  challenge   AWS WAF challenge did not settle
  blocked     page could not be read (403/429/network)

The probe never writes to the app database and uses no App code.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

BOOKING_URL = (
    'https://www.booking.com/hotel/sa/wa-jeddah.html'
    '?checkin=2026-11-06&checkout=2026-11-08'
    '&group_adults=2&group_children=0&no_rooms=1&selected_currency=SAR'
)
_CHALLENGE_RE = re.compile(
    r'challenge-container|awsWafCookieDomainList|__challenge_', re.I)
_BOT_ALERT = 'select dates to see this property'
_WAIT_SECONDS = 15


def find_chrome():
    explicit = (os.environ.get('BROWSER_EXECUTABLE_PATH') or '').strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    for candidate in (
            shutil.which('google-chrome'),
            shutil.which('google-chrome-stable'),
            shutil.which('chrome'),
            '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            '/opt/google/chrome/chrome',
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ''


def classify_booking_page(title, text, html, error=None):
    """Verdict for one loaded Booking page; no browser needed."""
    if error:
        return 'blocked'
    text = str(text or '')
    html = str(html or '')
    title = str(title or '')
    if 'b_bot' in html or _BOT_ALERT in text.casefold():
        return 'bot_page'
    if _CHALLENGE_RE.search(html) and len(text) < 1500:
        return 'challenge'
    has_price = bool(re.search(r'\bSAR\b|ريال|ر\.?\s?س', text))
    has_area = bool(re.search(r'[0-9]{2,3}\s*(?:م²|م2|m²|sqm)', text))
    has_date_markup = bool(re.search(
        r'searchbox-dates-container|date-display-field', html))
    if has_price or has_area or (has_date_markup and title):
        return 'ok'
    return 'unknown'


def start_chrome(executable, headless=True):
    profile = tempfile.mkdtemp(prefix='booking-probe-')
    args = [executable]
    if headless:
        args.append('--headless=new')
    args.extend([
        '--remote-debugging-port=0',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--disable-dev-shm-usage',
    ])
    args.extend((os.environ.get('BROWSER_LAUNCH_ARGS') or '').split())
    args.append('about:blank')
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    port_file = os.path.join(profile, 'DevToolsActivePort')
    port = None
    for _ in range(150):
        if proc.poll() is not None:
            break
        try:
            with open(port_file, encoding='utf-8') as handle:
                line = handle.readline().strip()
            port = int(line) if line else None
        except (OSError, ValueError):
            port = None
        if port:
            break
        time.sleep(0.1)
    if not port:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)
        raise RuntimeError('Chrome did not expose a DevTools port')
    return proc, profile, port


def _page_snapshot(page):
    try:
        html = page.content()
    except Exception:
        html = ''
    try:
        text = page.evaluate(
            'document.body ? document.body.innerText.slice(0, 30000) : ""')
    except Exception:
        text = ''
    try:
        title = page.title()
    except Exception:
        title = ''
    try:
        final_url = page.url
    except Exception:
        final_url = ''
    return title or '', text or '', html or '', final_url or ''


def run_probe(url, cdp=None, headless=True, executable=''):
    from playwright.sync_api import sync_playwright
    process = profile = None
    external = bool(cdp)
    if not cdp:
        executable = executable or find_chrome()
        if not executable:
            raise RuntimeError('Chrome not found; set BROWSER_EXECUTABLE_PATH')
        process, profile, port = start_chrome(executable, headless=headless)
        cdp = f'http://127.0.0.1:{port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp)
            context = (browser.contexts or [None])[0]
            if context is None:
                raise RuntimeError('CDP endpoint exposes no browser context')
            page = context.new_page()
            error = None
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=45000)
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            deadline = time.time() + _WAIT_SECONDS
            snapshot = _page_snapshot(page)
            while time.time() < deadline:
                title, text, html, final_url = snapshot
                if classify_booking_page(title, text, html, error) not in (
                        'challenge', 'unknown'):
                    break
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    pass
                snapshot = _page_snapshot(page)
            title, text, html, final_url = snapshot
            verdict = classify_booking_page(title, text, html, error)
            dates = re.findall(
                r'(?:check-in|checkout|تسجيل الوصول)[^\n]{0,80}', text, re.I)
            prices = re.findall(
                r'(?:SAR|ريال|ر\.?\s?س)\s*[0-9][0-9,.]*', text)[:5]
            areas = re.findall(
                r'[0-9]{2,3}(?:[.,][0-9])?\s*(?:م²|م2|m²|sqm)', text)[:5]
            result = {
                'verdict': verdict,
                'title': title[:200],
                'final_url': final_url,
                'chars': len(text),
                'challenge': bool(_CHALLENGE_RE.search(html)),
                'bot_class': 'b_bot' in html,
                'select_dates_alert': _BOT_ALERT in text.casefold(),
                'date_markup': bool(re.search(
                    r'searchbox-dates-container|date-display-field', html)),
                'prices': prices,
                'areas': areas,
                'dates': dates[:3],
                'error': error,
            }
            try:
                page.close()
            except Exception:
                pass
            if not external:
                try:
                    browser.close()
                except Exception:
                    pass
            return result
    finally:
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=8)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if profile:
            shutil.rmtree(profile, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=BOOKING_URL)
    parser.add_argument('--cdp', default='',
                        help='Existing CDP endpoint, e.g. http://127.0.0.1:9222')
    parser.add_argument('--headed', action='store_true',
                        help='Launch Chrome with a window instead of headless')
    parser.add_argument('--chrome', default='',
                        help='Chrome executable path (or BROWSER_EXECUTABLE_PATH)')
    args = parser.parse_args()
    try:
        result = run_probe(args.url, cdp=args.cdp,
                           headless=not args.headed,
                           executable=args.chrome)
    except Exception as exc:
        result = {'verdict': 'blocked',
                  'error': f'{type(exc).__name__}: {exc}'}
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('verdict') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
