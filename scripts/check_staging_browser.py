# -*- coding: utf-8 -*-
"""Staging viability probe for the browser-agent feature (task A7).

One SSH-safe shot on the target box (venv python): installs headless Chromium,
launches it, opens a page, and prints a verdict line the operator can paste
back. Local launch is tried as-is first, then retried with --no-sandbox args
since cPanel boxes usually lack the kernel sandbox; which mode succeeded is
part of the verdict because it decides the launch flags the app needs.

Verdicts:
  CHROMIUM_OK              local browser works (title + RSS printed)
  CHROMIUM_OK_NO_SANDBOX   works only with the no-sandbox arg set
  CHROMIUM_MISSING_LIBS    launch failed on shared libraries; the exact
                           loader/Playwright error is printed to plan around
  CHROMIUM_INSTALL_FAILED  `playwright install chromium` failed
  CHROMIUM_LAUNCH_FAILED   launch failed for a non-library reason
  CHROMIUM_NAV_FAILED      browser launched but the page never loaded
  PLAYWRIGHT_NOT_INSTALLED pip package missing in this interpreter

When BROWSER_WS_ENDPOINT is set, a remote-CDP check runs after the local one
so the fallback verdict lands in the same output.
"""
import _bootstrap  # noqa: F401  (repo-root sys.path wiring)
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys

PAGE_URL = 'https://example.com/'
NAV_TIMEOUT_MS = 30000
NO_SANDBOX_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
_LIB_FAIL_RE = re.compile(
    r'missing dependencies|error while loading shared libraries|'
    r'cannot open shared object file|libraries.*not found', re.I)


def _mem_available_mb():
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def _chromium_rss_mb():
    """Sum VmRSS of every running Chromium process; None off-Linux."""
    if not os.path.isdir('/proc'):
        return None
    total_kb = 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/comm') as fh:
                comm = fh.read().strip().lower()
            if not any(k in comm for k in ('chrome', 'chromium', 'headless')):
                with open(f'/proc/{pid}/cmdline', 'rb') as fh:
                    if b'ms-playwright' not in fh.read():
                        continue
            with open(f'/proc/{pid}/status') as fh:
                for line in fh:
                    if line.startswith('VmRSS:'):
                        total_kb += int(line.split()[1])
                        break
        except OSError:
            continue
    return total_kb // 1024


def _install_chromium():
    print('[probe] playwright install chromium ...', flush=True)
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            timeout=900)
    except Exception as exc:
        return f'install raised {type(exc).__name__}: {exc}'
    return None if proc.returncode == 0 else f'install exit code {proc.returncode}'


def _try_launch(pw, extra_args=None):
    """Returns (browser, error_text). Never raises."""
    try:
        kwargs = {'headless': True}
        if extra_args:
            kwargs['args'] = extra_args
        return pw.chromium.launch(**kwargs), None
    except Exception as exc:
        return None, f'{type(exc).__name__}: {exc}'


def _probe_page(browser):
    """Open PAGE_URL; returns (title, error_text)."""
    try:
        page = browser.new_page()
        page.goto(PAGE_URL, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        return (page.title() or '').strip(), None
    except Exception as exc:
        return None, f'{type(exc).__name__}: {exc}'


def _cdp_check(pw):
    endpoint = os.environ.get('BROWSER_WS_ENDPOINT', '').strip()
    if not endpoint:
        return
    print('[probe] BROWSER_WS_ENDPOINT set - checking remote CDP fallback ...', flush=True)
    browser = None
    try:
        browser = pw.chromium.connect_over_cdp(endpoint, timeout=20000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.goto(PAGE_URL, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        print(f'[probe] CDP_OK title={page.title()!r}', flush=True)
    except Exception as exc:
        print(f'[probe] CDP_FAILED {type(exc).__name__}: {exc}', flush=True)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def main():
    print(f'[probe] python={sys.version.split()[0]} platform={platform.system()} {platform.release()}', flush=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('VERDICT: PLAYWRIGHT_NOT_INSTALLED (pip install playwright)', flush=True)
        return 1
    print(f'[probe] playwright={importlib.metadata.version("playwright")}', flush=True)

    err = _install_chromium()
    if err:
        print(f'VERDICT: CHROMIUM_INSTALL_FAILED - {err}', flush=True)
        return 1

    cache = os.path.expanduser(os.environ.get(
        'PLAYWRIGHT_BROWSERS_PATH', '~/.cache/ms-playwright'))
    try:
        free_mb = shutil.disk_usage(cache if os.path.isdir(cache) else os.path.dirname(cache) or '/').free // (1024 * 1024)
        print(f'[probe] disk_free={free_mb}MB at {cache}', flush=True)
    except OSError:
        pass

    avail_before = _mem_available_mb()
    verdict = None
    with sync_playwright() as pw:
        browser, launch_err = _try_launch(pw)
        mode = 'default'
        if browser is None and not _LIB_FAIL_RE.search(launch_err or ''):
            print(f'[probe] default launch failed, retrying no-sandbox: {launch_err}', flush=True)
            browser, launch_err = _try_launch(pw, NO_SANDBOX_ARGS)
            mode = 'no-sandbox'
        if browser is None:
            if _LIB_FAIL_RE.search(launch_err or ''):
                print('[probe] missing library detail:', flush=True)
                print(launch_err, flush=True)
                verdict = 'CHROMIUM_MISSING_LIBS'
            else:
                print(f'[probe] launch error: {launch_err}', flush=True)
                verdict = 'CHROMIUM_LAUNCH_FAILED'
        else:
            title, nav_err = _probe_page(browser)
            if nav_err:
                print(f'[probe] nav error: {nav_err}', flush=True)
                verdict = 'CHROMIUM_NAV_FAILED'
            else:
                rss_mb = _chromium_rss_mb()
                avail_after = _mem_available_mb()
                print(f'[probe] title={title!r}', flush=True)
                print(f'[probe] chromium_rss={rss_mb}MB' if rss_mb is not None
                      else '[probe] chromium_rss=n/a (non-Linux)', flush=True)
                if avail_before is not None and avail_after is not None:
                    print(f'[probe] mem_available {avail_before}MB -> {avail_after}MB', flush=True)
                verdict = 'CHROMIUM_OK_NO_SANDBOX' if mode == 'no-sandbox' else 'CHROMIUM_OK'
            try:
                browser.close()
            except Exception:
                pass
        _cdp_check(pw)

    print(f'VERDICT: {verdict}', flush=True)
    return 0 if verdict and verdict.startswith('CHROMIUM_OK') else 1


if __name__ == '__main__':
    sys.exit(main())
