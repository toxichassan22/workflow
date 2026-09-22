
def _strip_hidden_watermark_overlays(html):
    """Drop hidden watermark layers from an export copy.

    The saved slide keeps the hidden layer for a later show; the exported
    file must not draw it. Visible layers pass through untouched.
    """
    if not html or 'watermark' not in str(html).lower():
        return html
    source = str(html)

    def _drop_if_hidden(match):
        overlay = match.group(0)
        tag_end = overlay.find('>')
        tag = overlay[:tag_end + 1] if tag_end != -1 else overlay
        hidden_attr = re.search(
            r'data-watermark-visible\s*=\s*["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        if hidden_attr and hidden_attr.group(1).strip().lower() == 'false':
            return ''
        if re.search(r'display\s*:\s*none', tag, flags=re.IGNORECASE):
            return ''
        return overlay

    source = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div\s*>',
        _drop_if_hidden, source, flags=re.IGNORECASE,
    )
    return re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div\s*>',
        _drop_if_hidden, source, flags=re.IGNORECASE,
    )


BASE_DIR = Path(__file__).resolve().parent

# Which renderer wrote the last deck PDF. The PyMuPDF fallback keeps the page
# count but shifts every 1280px slide right (~22px white strip on the left,
# clipped content on the right) and writes 1280x720pt pages instead of
# Chromium's 960x540pt, so a file it produced must never pass as a normal
# export. The export route reports this value; the server log states it too.
LAST_PDF_ENGINE = ''

CHROMIUM_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--font-render-hinting=none",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--mute-audio",
    "--no-first-run",
    "--js-flags=--max-old-space-size=256",
]

# Where a host-wide browser lives when Playwright's bundled download cannot
# run (shared hosting without the OS libraries Chromium needs). An explicit
# CHROMIUM_PATH (or CHROME_PATH) wins; the well-known locations are probed
# after Playwright's own binary.
_SYSTEM_CHROMIUM_CANDIDATES = (
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/opt/google/chrome/chrome',
)


def _configure_chromium_environment():
    """Ensure sideloaded libraries in ~/chromium-libs are in LD_LIBRARY_PATH."""
    candidates = [
        str(Path.home() / 'chromium-libs' / 'usr' / 'lib64'),
        str(Path.home() / 'chromium-libs' / 'lib64'),
        str(Path.home() / 'chromium-libs'),
        '/home/landloom/chromium-libs/usr/lib64',
        '/home/landloom/chromium-libs/lib64',
        '/home/landloom/chromium-libs',
    ]
    current = os.environ.get('LD_LIBRARY_PATH', '')
    existing = current.split(':') if current else []
    changed = False
    for c in candidates:
        if os.path.isdir(c) and c not in existing:
            existing.insert(0, c)
            changed = True
    if changed:
        os.environ['LD_LIBRARY_PATH'] = ':'.join(existing)

_configure_chromium_environment()


def _extra_chromium_args():
    """Admin-supplied flags without a redeploy (e.g. '--disable-software-rasterizer').

    Read from CHROMIUM_EXTRA_ARGS as whitespace-separated tokens and appended
    to every launch attempt, so flag combinations can be iterated from the
    host environment with only an app restart between tries.
    """
    return (os.environ.get('CHROMIUM_EXTRA_ARGS') or '').split()


def _export_image_limits():
    try:
        max_side = int(os.environ.get('EXPORT_IMAGE_MAX_SIDE') or 1280)
    except ValueError:
        max_side = 1280
    try:
        quality = int(os.environ.get('EXPORT_IMAGE_JPEG_QUALITY') or 82)
    except ValueError:
        quality = 82
    return max(320, max_side), min(95, max(50, quality))


def fit_image_bytes(data):
    """Downscale an oversized export image to display size (never upscale).

    Slides render at 1280x720, so a 4000px source only adds weight: a ~2.5MB
    PNG photo becomes ~200KB JPEG with no visible difference on the page.
    Returns the original bytes whenever fitting would not help or fails, so
    this can wrap any image path without risking the export itself.
    """
    if not data or len(data) < 150 * 1024:
        return data
    try:
        from io import BytesIO as _BytesIO
        from PIL import Image as _Image
        with _Image.open(_BytesIO(data)) as handle:
            handle.load()
            width, height = handle.size
            mode = handle.mode
            has_alpha = (
                mode in ('RGBA', 'LA', 'PA')
                or (mode == 'P' and 'transparency' in handle.info)
            )
            source_format = str(handle.format or '').upper()
            picture = handle.convert('RGB' if not has_alpha else 'RGBA')
            if has_alpha:
                try:
                    extrema = picture.getextrema()
                    if picture.mode == 'RGBA' and len(extrema) >= 4 and isinstance(extrema[3], tuple):
                        if extrema[3][0] >= 255:
                            picture = picture.convert('RGB')
                            has_alpha = False
                except Exception:
                    pass
        max_side, quality = _export_image_limits()
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / float(longest)
            picture = picture.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                _Image.LANCZOS,
            )
        photo_like = (source_format in ('JPEG', 'JPG', 'WEBP') or len(data) > 400 * 1024)
        out = _BytesIO()
        if has_alpha or not photo_like:
            if longest <= max_side and source_format == 'PNG' and len(data) <= 400 * 1024:
                return data
            picture.save(out, format='PNG')
        else:
            picture.save(out, format='JPEG', quality=quality, optimize=True,
                         progressive=True)
        fitted = out.getvalue()
        return fitted if 0 < len(fitted) < len(data) else data
    except Exception:
        return data


def _local_file_bytes_from_url(url):
    from urllib.parse import unquote, urlparse
    path = Path(unquote(urlparse(url).path))
    if os.name == 'nt' and len(str(path)) > 2 and str(path)[1] == ':':
        path = Path(str(path)[1:])
    try:
        if path.is_file() and path.stat().st_size:
            return path.read_bytes(), path.suffix.lower()
    except OSError:
        pass
    return None, ''


def fit_export_images_in_html(html, tmp_root):
    """Rewrite oversized image sources in export HTML to fitted copies.

    ``file://`` URLs become fitted files under tmp_root (reused by content
    hash, which also lets Chromium deduplicate them into one object), and
    oversized ``data:`` URIs are re-encoded smaller inline. Anything else —
    remote URLs, missing files, small images — is left untouched.
    """
    if not html or 'img' not in html.lower() and 'url(' not in html.lower():
        return html
    import base64 as _base64
    import hashlib as _hashlib
    fitted_files = {}

    def _fit_data_uri(url):
        header, _, payload = url.partition(',')
        if ';base64' not in header or not payload:
            return None
        try:
            raw = _base64.b64decode(payload)
        except Exception:
            return None
        fitted = fit_image_bytes(raw)
        if fitted == raw:
            return None
        mime = 'image/png' if fitted[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
        return f'data:{mime};base64,' + _base64.b64encode(fitted).decode('ascii')

    def _fit_file_url(url):
        clean = url.split('?')[0].split('#')[0]
        if clean in fitted_files:
            return fitted_files[clean]
        raw, _suffix = _local_file_bytes_from_url(clean)
        if not raw:
            return None
        fitted = fit_image_bytes(raw)
        if fitted == raw:
            fitted_files[clean] = None
            return None
        ext = '.png' if fitted[:8] == b'\x89PNG\r\n\x1a\n' else '.jpg'
        name = 'export-img-' + _hashlib.md5(fitted).hexdigest() + ext
        target = Path(tmp_root) / name
        try:
            if not target.is_file():
                target.write_bytes(fitted)
        except OSError:
            return None
        uri = target.as_uri()
        fitted_files[clean] = uri
        return uri

    def _replace_attribute(match):
        replacement = _fit_data_uri(match.group('url')) if match.group('url').lower().startswith('data:') else _fit_file_url(match.group('url'))
        if not replacement:
            return match.group(0)
        return match.group('prefix') + replacement + match.group('quote')

    def _replace_css_url(match):
        replacement = _fit_data_uri(match.group('url')) if match.group('url').lower().startswith('data:') else _fit_file_url(match.group('url'))
        if not replacement:
            return match.group(0)
        quote = match.group('q') or '"'
        return f'url({quote}{replacement}{quote})'

    html = re.sub(
        r'''(?P<prefix>(?:src|href)\s*=\s*["'])(?P<url>(?:file://[^"']+|data:image/[^"']+))(?P<quote>["'])''',
        _replace_attribute, html, flags=re.IGNORECASE)
    html = re.sub(
        r'''url\(\s*(?P<q>["']?)(?P<url>(?:file://[^)"']+|data:image/[^)"']+))(?P=q)\s*\)''',
        _replace_css_url, html, flags=re.IGNORECASE)
    return html


def _chromium_executable_candidates():
    seen = []
    for env_name in ('CHROMIUM_PATH', 'CHROME_PATH'):
        configured = (os.environ.get(env_name) or '').strip()
        if configured and configured not in seen:
            seen.append(configured)
    import shutil
    for name in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable'):
        found = shutil.which(name)
        if found and found not in seen:
            seen.append(found)
    for path in _SYSTEM_CHROMIUM_CANDIDATES:
        if path not in seen:
            seen.append(path)
    # Also probe playwright-installed binaries in ~/.cache/ms-playwright
    cache_root = Path.home() / '.cache' / 'ms-playwright'
    if cache_root.is_dir():
        for pattern in ('**/headless_shell', '**/chrome', '**/chrome.exe', '**/headless_shell.exe'):
            try:
                for p in cache_root.glob(pattern):
                    sp = str(p)
                    if sp not in seen and p.is_file() and os.access(p, os.X_OK):
                        seen.append(sp)
            except Exception:
                pass
    return [path for path in seen if path and os.path.isfile(path)]


def short_browser_error(exc, head=130, tail=260):
    """One-line launch error that keeps the diagnosis, which lives at the end.

    Playwright's message opens with the launching command line (hundreds of
    characters of flags) and only names the missing library — or the real
    crash reason — in its last lines. A plain [:300] slice therefore keeps the
    flags and eats the diagnosis, which is exactly what hid a dead browser
    behind "Target page, context or browser has been closed".
    """
    text = f'{type(exc).__name__}: {exc}'.replace('\n', ' ').replace('\r', ' ')
    text = ' '.join(text.split())
    if len(text) > head + tail + 5:
        return text[:head] + ' ... ' + text[-tail:]
    return text


def _launch_chromium(playwright):
    """Launch a Chromium for deck rendering, trying harder than the default.

    Playwright's bundled binary is tried first with the exact arguments the
    export has always used. A downloaded binary that dies on start is the
    usual shared-hosting state: the file exists, so reinstalling changes
    nothing. The next attempts cover the known container rescues
    (single-process without zygote, full-Chromium new headless instead of the
    headless shell), then an admin-provided CHROMIUM_PATH and the host-wide
    browser locations. Returns the (browser, description) pair; raises
    RuntimeError naming every attempt so the server log — not a silently
    degraded PDF — carries the failure. CHROMIUM_EXTRA_ARGS tokens join every
    attempt, so flags can be iterated from the host environment.
    """
    base_args = list(CHROMIUM_LAUNCH_ARGS) + _extra_chromium_args()
    errors = []
    try:
        browser = playwright.chromium.launch(args=list(base_args))
        return browser, 'bundled-chromium'
    except Exception as exc:
        errors.append(f'bundled: {short_browser_error(exc)}')
    try:
        browser = playwright.chromium.launch(
            args=list(base_args) + ['--no-zygote', '--single-process']
        )
        return browser, 'bundled-chromium-single-process'
    except Exception as exc:
        errors.append(f'bundled-single-process: {short_browser_error(exc)}')
    previous_headless_new = os.environ.get('PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW')
    os.environ['PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW'] = '1'
    try:
        try:
            browser = playwright.chromium.launch(args=list(base_args))
            return browser, 'bundled-chromium-headless-new'
        except Exception as exc:
            errors.append(f'bundled-headless-new: {short_browser_error(exc)}')
    finally:
        if previous_headless_new is None:
            os.environ.pop('PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW', None)
        else:
            os.environ['PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW'] = previous_headless_new
    for candidate in _chromium_executable_candidates():
        try:
            browser = playwright.chromium.launch(
                args=list(base_args), executable_path=candidate
            )
            return browser, f'system-chromium:{candidate}'
        except Exception as exc:
            errors.append(f'{candidate}: {short_browser_error(exc)}')
    raise RuntimeError('no launchable Chromium (' + ' | '.join(errors[:8]) + ')')


# Past this many slides a single Chromium document peaks small-host account
# limits (the worker is SIGKilled with no traceback and no log line), while
# the same deck prints fine in small groups.
_CHUNKED_PRINT_THRESHOLD = 10
_CHUNKED_PRINT_SIZE = 6


def _print_chunk_size(slide_count):
    """How many slides go into one Chromium print document (0 = single print).

    PDF_PRINT_CHUNK overrides: a positive integer forces that group size,
    'off'/'0' keeps the historical single print. By default ('auto') decks
    longer than _CHUNKED_PRINT_THRESHOLD slides print in groups of
    _CHUNKED_PRINT_SIZE and merge, keeping peak renderer memory flat.
    """
    raw = (os.environ.get('PDF_PRINT_CHUNK') or 'auto').strip().lower()
    if raw in ('off', '0', 'no', 'false'):
        return 0
    if raw not in ('', 'auto'):
        try:
            forced = int(raw)
            return forced if forced > 0 else 0
        except ValueError:
            pass
    if (slide_count or 0) > _CHUNKED_PRINT_THRESHOLD:
        return _CHUNKED_PRINT_SIZE
    return 0


def _chunk_document_html(chunk_slides, layout_css, font_css):
    body = "\n".join(f'<div class="pdf-export-page">{slide}</div>' for slide in chunk_slides)
    return f"""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<style>{layout_css}</style>
</head>
<body id="pdf-export-root" style="margin:0;padding:0;background:#fff;">{body}<style>{font_css}</style></body>
</html>"""


def _probe_print_layout(page, offset=0):
    """Measure the printed layout, naming slides by their deck-wide number."""
    try:
        page.emulate_media(media='print')
        report = page.evaluate(
            """() => Array.from(document.querySelectorAll('.slide')).map((el, i) => {
                const cs = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return {
                    index: i + 1,
                    position: cs.position,
                    display: cs.display,
                    cssFloat: cs.float,
                    breakAfter: cs.breakAfter || cs.pageBreakAfter,
                    height: Math.round(rect.height),
                    width: Math.round(rect.width),
                };
            })"""
        )
    except Exception as error:
        print(f"[PDF] layout probe failed: {error}")
        return []
    for item in report or []:
        if isinstance(item, dict) and isinstance(item.get('index'), int):
            item['index'] += offset
    return report


def _generate_pdf_chunked(playwright, slides, layout_css, font_css, out_path, tmp_root):
    """Print a long deck in small documents and merge, keeping memory flat.

    Each group loads in a fresh page that is closed before the next group
    starts, so peak renderer memory stays near one group instead of the whole
    deck. Returns (produced_path, layout_report) like the single print.
    """
    chunk_size = _print_chunk_size(len(slides)) or len(slides)
    groups = [slides[i:i + chunk_size] for i in range(0, len(slides), chunk_size)]
    print(f"[PDF] Printing {len(slides)} slides in {len(groups)} Chromium documents...")
    browser, launch_how = _launch_chromium(playwright)
    print(f"[PDF] Chromium ready via {launch_how}")
    chunk_paths = []
    layout_report = []
    try:
        for number, group in enumerate(groups, 1):
            html_path = tmp_root / f'chunk-{number}.html'
            html_path.write_text(
                _chunk_document_html(group, layout_css, font_css), encoding='utf-8')
            page = browser.new_page()
            _install_export_request_guard(page)
            try:
                page.set_viewport_size({"width": 1280, "height": 720})
                page.goto(html_path.as_uri(), wait_until="load", timeout=30000)
                try:
                    page.evaluate("() => document.fonts.ready")
                    page.wait_for_function(
                        "() => Array.from(document.images).every(i => i.complete)",
                        timeout=30000,
                    )
                except Exception:
                    pass
                layout_report.extend(
                    _probe_print_layout(page, offset=(number - 1) * chunk_size))
                chunk_path = tmp_root / f'chunk-{number}.pdf'
                print(f"[PDF] Printing chunk {number}/{len(groups)} ({len(group)} slides)...")
                page.pdf(
                    path=str(chunk_path),
                    width="1280px",
                    height="720px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
                chunk_paths.append(chunk_path)
            finally:
                page.close()
    finally:
        try:
            browser.close()
        except Exception:
            pass
    import fitz
    merged_path = tmp_root / 'chunked-merged.pdf'
    output = fitz.open()
    try:
        for chunk_path in chunk_paths:
            with fitz.open(str(chunk_path)) as source:
                output.insert_pdf(source)
        output.save(str(merged_path))
    finally:
        output.close()
    _replace_output_file(merged_path, out_path)
    return str(out_path), layout_report


def _generate_pdf_with_fitz(html, out_path, slides=None, layout_css='', font_css=''):
    """Pure-Python fallback using PyMuPDF when Playwright is unavailable."""
    print("[FONT] WARNING: PyMuPDF fallback cannot render @font-face/base64 fonts; custom font may not apply")
    import fitz
    fitz_base_css = """
@page { size: 1280px 720px; margin: 0; }
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #pdf-export-root { margin: 0 !important; padding: 0 !important; width: 1280px !important; height: 720px !important; overflow: hidden !important; background: #fff; direction: rtl; }
.pdf-export-page { width: 1280px !important; height: 720px !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important; position: relative !important; display: block !important; }
.slide { width: 1280px !important; height: 720px !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important; position: relative !important; display: block !important; }
img { max-width: 100%; max-height: 100%; object-fit: contain; }
svg[data-chart], svg.combo-chart { max-width: 100% !important; max-height: 320px !important; height: auto !important; display: block; }
"""
    combined_css = fitz_base_css + "\n" + (layout_css or '')
    if slides:
        output = fitz.open()
        try:
            for slide in slides:
                page_html = f'''<!DOCTYPE html>
<html dir="rtl"><head><meta charset="utf-8"><style>{combined_css}</style></head>
<body id="pdf-export-root" style="margin:0;padding:0;background:#fff;">
<div class="pdf-export-page">{slide}</div><style>{font_css}</style></body></html>'''
                source = fitz.open('html', page_html.encode('utf-8'), width=1280, height=720)
                page_pdf = None
                try:
                    if source.page_count:
                        page_pdf = fitz.open('pdf', source.convert_to_pdf())
                        output.insert_pdf(page_pdf, from_page=0, to_page=0)
                finally:
                    if page_pdf is not None:
                        page_pdf.close()
                    source.close()
            if os.path.exists(out_path):
                os.unlink(out_path)
            output.save(out_path)
        finally:
            output.close()
        return str(out_path)
    # Render HTML to a 1280x720 pt page; may not be pixel-perfect but avoids 502s.
    if '<head>' in html:
        html_with_page = html.replace('<head>', f'<head><style>{fitz_base_css}</style>', 1)
    else:
        html_with_page = f'<style>{fitz_base_css}</style>' + html
    src = fitz.open('html', html_with_page.encode('utf-8'), width=1280, height=720)
    src.save(out_path)
    src.close()
    return str(out_path)


def _pdf_page_count(pdf_path):
    import fitz
    with fitz.open(str(pdf_path)) as document:
        return document.page_count


def _replace_output_file(source_path, out_path):
    out_path = Path(out_path)
    descriptor, staged_path = tempfile.mkstemp(
        dir=str(out_path.parent), prefix=out_path.stem + '-', suffix='.tmp'
    )
    os.close(descriptor)
    try:
        shutil.copyfile(source_path, staged_path)
        os.replace(staged_path, out_path)
    finally:
        if os.path.exists(staged_path):
            os.unlink(staged_path)


def _generate_pdf_pages_with_playwright(page, slides, layout_css, font_css, out_path, tmp_dir):
    page_paths = []
    font_path = Path(tmp_dir) / 'isolated-font.css'
    font_path.write_text(font_css, encoding='utf-8')
    for index, slide in enumerate(slides):
        html_path = Path(tmp_dir) / f'isolated-{index + 1}.html'
        page_html = f'''<!DOCTYPE html>
<html dir="rtl"><head><meta charset="utf-8"><style>{layout_css}</style>
<link rel="stylesheet" href="{font_path.as_uri()}"></head>
<body id="pdf-export-root" style="margin:0;padding:0;background:#fff;">
<div class="pdf-export-page">{slide}</div></body></html>'''
        html_path.write_text(page_html, encoding='utf-8')
        page.goto(html_path.as_uri(), wait_until='load', timeout=30000)
        page.emulate_media(media='print')
        try:
            page.evaluate("() => document.fonts.ready")
            page.wait_for_function(
                "() => Array.from(document.images).every(image => image.complete)",
                timeout=30000,
            )
        except Exception:
            pass
        page.evaluate(
            """() => {
                const force = (element, rules) => {
                    for (const [name, value] of Object.entries(rules)) {
                        element.style.setProperty(name, value, 'important');
                    }
                };
                const root = document.getElementById('pdf-export-root');
                const sheet = root && root.querySelector('.pdf-export-page');
                if (!root || !sheet) throw new Error('isolated pdf export page is missing');
                const rootRules = {
                    display: 'block', position: 'static', float: 'none', margin: '0', padding: '0',
                    width: '1280px', height: '720px', overflow: 'hidden', columns: 'auto',
                    'column-count': 'auto', 'column-width': 'auto', 'grid-template-columns': 'none',
                    'grid-template-rows': 'none', gap: '0', transform: 'none', zoom: '1'
                };
                force(document.documentElement, rootRules);
                force(root, rootRules);
                force(sheet, {
                    display: 'block', position: 'relative', float: 'none', margin: '0', padding: '0',
                    width: '1280px', height: '720px', inset: 'auto', transform: 'none', zoom: '1',
                    overflow: 'hidden', visibility: 'visible', opacity: '1', 'break-before': 'auto',
                    'break-after': 'auto', 'page-break-before': 'auto', 'page-break-after': 'auto'
                });
            }"""
        )
        page_path = Path(tmp_dir) / f'isolated-{index + 1}.pdf'
        page.pdf(
            path=str(page_path),
            width="1280px",
            height="720px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            page_ranges="1",
        )
        page_paths.append(page_path)

    import fitz
    merged_path = Path(tmp_dir) / 'isolated-merged.pdf'
    output = fitz.open()
    try:
        for page_path in page_paths:
            with fitz.open(str(page_path)) as source:
                output.insert_pdf(source, from_page=0, to_page=0)
        output.save(str(merged_path))
    finally:
        output.close()
    _replace_output_file(merged_path, out_path)
    return str(out_path)
