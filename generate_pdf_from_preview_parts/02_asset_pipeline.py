

def _resolve_asset_urls(html):
    """Convert relative uploads/, assets/, and tenant-assets/ references to absolute file URIs."""
    if not html:
        return html
    base = BASE_DIR.as_uri()
    prefixes = [
        ('"uploads/', f'"{base}/uploads/'),
        ("'uploads/", f"'{base}/uploads/"),
        ('"assets/', f'"{base}/assets/'),
        ("'assets/", f"'{base}/assets/"),
        ('"/uploads/', f'"{base}/uploads/'),
        ("'/uploads/", f"'{base}/uploads/"),
        ('"/assets/', f'"{base}/assets/'),
        ("'/assets/", f"'{base}/assets/"),
        ('url("uploads/', f'url("{base}/uploads/'),
        ("url('uploads/", f"url('{base}/uploads/"),
        ('url("assets/', f'url("{base}/assets/'),
        ("url('assets/", f"url('{base}/assets/"),
        ('url(uploads/', f'url({base}/uploads/'),
        ('url(assets/', f'url({base}/assets/'),
        ('url(/uploads/', f'url({base}/uploads/'),
        ('url(/assets/', f'url({base}/assets/'),
        ('"/tenant-assets/', f'"{base}/uploads/'),
        ("'/tenant-assets/", f"'{base}/uploads/"),
        ('url("/tenant-assets/', f'url("{base}/uploads/'),
        ("url('/tenant-assets/", f"url('{base}/uploads/"),
        ('url(/tenant-assets/', f'url({base}/uploads/'),
        ('"/tenant-assets/', f'"{base}/uploads/'),
    ]
    for old, new in prefixes:
        html = html.replace(old, new)
    # Strip cache-busting query strings from local asset URLs so Playwright can load them
    html = re.sub(r'((?:' + re.escape(base) + r')?/uploads/[^"\'\)]+)\?[^"\'\)]+', r'\1', html)
    return html


_PROJECT_FILE_URL_RE = re.compile(
    r'(?P<url>(?:https?://[^"\'\s)<>]+)?/api/project-files/'
    r'(?P<file_id>[^"\'\s)<>/?#]+)(?:\?[^"\'\s)<>]*)?(?:#[^"\'\s)<>]*)?)',
    re.IGNORECASE,
)


def _local_project_file_path(tenant_id, file_id):
    """Return a tenant-scoped local image path for an authenticated project-file URL."""
    if not tenant_id or not file_id:
        return None
    try:
        import db
        stored = db.get_project_file(str(tenant_id), str(file_id))
    except Exception as exc:
        print(f'[EXPORT] Could not resolve project file {file_id}: {exc}')
        return None
    if not stored or not str(stored.get('mime_type') or '').lower().startswith('image/'):
        return None

    storage_path = Path(os.path.realpath(str(stored.get('storage_path') or '')))
    tenant_root = Path(os.path.realpath(BASE_DIR / 'uploads' / str(tenant_id)))
    try:
        if os.path.commonpath([str(tenant_root), str(storage_path)]) != str(tenant_root):
            return None
    except ValueError:
        return None
    return storage_path if storage_path.is_file() else None


def _resolve_project_file_urls(html, tenant_id):
    """Replace authenticated project-file image URLs with local file URIs for offline export.

    The editor can load ``/api/project-files/<id>`` with the user's auth header. Exported HTML
    is rendered from a ``file:`` URL, where that route is neither relative to the application nor
    authenticated. Resolving the record here also keeps legacy presentations exportable after the
    client has migrated to durable ``/uploads/`` image URLs.
    """
    if not html or not tenant_id:
        return html
    resolved = {}

    def replace(match):
        file_id = match.group('file_id')
        if file_id not in resolved:
            path = _local_project_file_path(tenant_id, file_id)
            resolved[file_id] = path.as_uri() if path else ''
        return resolved[file_id] or match.group('url')

    return _PROJECT_FILE_URL_RE.sub(replace, html)


# ---------------------------------------------------------------------------
# ISS-019: export resource policy
#
# Slide HTML is stored user input: it can carry ``file://``, ``http(s)://`` or
# relative references that would make the renderer read outside the tenant —
# or reach the host's internal network — when a slide is exported. Everything
# the export may legitimately need resolves to a ``data:`` URI or a file under
# one of the allowed roots below; anything else is stripped so the tag renders
# broken instead of leaking bytes.
# ---------------------------------------------------------------------------

# Google font CSS/face fetches are the only remote reads an export may make —
# ``build_font_css`` emits those @imports and font-status documents them.
_EXPORT_REMOTE_HOSTS = frozenset({'fonts.googleapis.com', 'fonts.gstatic.com'})


def _export_local_roots(tenant_id, extra_roots=(), base_dir=None):
    """Directories a ``file:`` or relative resource may resolve under."""
    base = Path(base_dir) if base_dir else BASE_DIR
    roots = [base / 'assets', base / 'fonts']
    tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or ''))
    if tenant:
        roots += [
            base / 'uploads' / tenant,
            base / 'uploads' / 'creative' / tenant,
            base / 'uploads' / 'training' / tenant,
        ]
    for extra in extra_roots or ():
        roots.append(Path(extra))
    return roots


def _export_allowed_local_path(path, tenant_id, extra_roots=(), base_dir=None):
    """True when ``path`` resolves under an export-allowed root (ISS-019).

    ``uploads/<tenant>``, ``uploads/creative/<tenant>`` and
    ``uploads/training/<tenant>`` are tenant namespaces; ``uploads/maps/`` is
    shared on disk, so a map file is allowed only when the tenant's
    ``map_images`` ledger points at it. Bundled ``assets/`` and ``fonts/``
    belong to the application itself.
    """
    base = Path(base_dir) if base_dir else BASE_DIR
    try:
        real = os.path.realpath(str(path))
    except Exception:
        return False
    for root in _export_local_roots(tenant_id, extra_roots, base_dir=base):
        try:
            root_real = os.path.realpath(str(root))
            if os.path.commonpath([root_real, real]) == root_real:
                return True
        except (ValueError, OSError):
            continue
    tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or ''))
    if tenant:
        try:
            maps_real = os.path.realpath(str(base / 'uploads' / 'maps'))
            if os.path.commonpath([maps_real, real]) == maps_real:
                import db
                for row in db.get_map_images(str(tenant_id)) or []:
                    stored = row.get('file_path')
                    if stored and os.path.realpath(stored) == real:
                        return True
        except Exception:
            pass
    return False


def _export_url_to_local_path(url):
    """Parse a ``file://`` URL or site path into a local path under BASE_DIR."""
    clean = str(url).split('?')[0].split('#')[0].strip()
    if clean.lower().startswith('file://'):
        clean = unquote(urlparse(clean).path)
        # Windows file URIs look like file:///D:/... -> urlparse gives /D:/...
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:', clean):
            clean = clean[1:]
        return Path(clean)
    # Anything without a scheme is interpreted the way the app serves it —
    # rooted at BASE_DIR — so '/uploads/x' and 'uploads/x' agree.
    return BASE_DIR / clean.lstrip('/')


def _export_url_allowed(url, tenant_id, extra_roots=()):
    """ISS-019: whether one resource reference may survive into export HTML."""
    value = str(url or '').strip()
    if not value or value.startswith('#'):
        return True
    low = value.lower()
    if low.startswith('data:'):
        return low.startswith('data:image/') or low.startswith('data:font/')
    if low.startswith('//'):
        value = 'https:' + value
        low = value.lower()
    if low.startswith(('http://', 'https://')):
        try:
            host = urlparse(value).hostname or ''
        except Exception:
            return False
        return host.lower() in _EXPORT_REMOTE_HOSTS
    if low.startswith('file:'):
        # The resolvers above legitimately emit file: URIs for tenant uploads,
        # project files and bundled assets — the local-path policy still gates
        # them by resolved location, so file:///etc/passwd keeps failing.
        return _export_allowed_local_path(
            _export_url_to_local_path(value), tenant_id, extra_roots)
    first = low.split('/', 1)[0]
    if ':' in first:
        return False  # javascript:, vbscript:, unknown schemes
    return _export_allowed_local_path(
        _export_url_to_local_path(value), tenant_id, extra_roots)


_EXPORT_ATTR_URL_RE = re.compile(
    r'''(?P<prefix>[\w:-]*(?:src|href|poster|srcset)\s*=\s*)(?P<quote>["'])(?P<url>.*?)(?P=quote)''',
    re.IGNORECASE | re.DOTALL)
_EXPORT_CSS_URL_RE = re.compile(
    r'''url\(\s*(?P<q>["']?)(?P<url>[^)"']+)(?P=q)\s*\)''', re.IGNORECASE)
_EXPORT_IMPORT_RE = re.compile(r'''@import\s+(["'])(?P<url>[^"']+)\1''', re.IGNORECASE)


def _sanitize_export_resource_urls(html, tenant_id, tmp_root=None):
    """ISS-019: drop every resource reference the export may not follow.

    Runs after the project-file/asset resolvers have produced ``file:`` URIs,
    so legitimate tenant images keep working while hostile ``file://`` reads,
    remote fetches and ``..`` traversals are emptied.
    """
    if not html:
        return html
    extra = (tmp_root,) if tmp_root else ()

    def _keep(url):
        return _export_url_allowed(url, tenant_id, extra)

    def _attr(match):
        url = match.group('url')
        if 'srcset' in match.group('prefix').lower():
            kept = []
            for candidate in url.split(','):
                candidate = candidate.strip()
                if not candidate:
                    continue
                source, _, descriptor = candidate.partition(' ')
                if _keep(source.strip()):
                    kept.append((source.strip() + ' ' + descriptor.strip()).strip())
            url = ', '.join(kept)
            return match.group('prefix') + match.group('quote') + url + match.group('quote')
        if _keep(url.strip()):
            return match.group(0)
        print(f'[EXPORT] blocked resource url: {url.strip()[:120]}')
        return match.group('prefix') + match.group('quote') + match.group('quote')

    def _css(match):
        url = match.group('url').strip()
        if _keep(url):
            return match.group(0)
        print(f'[EXPORT] blocked css url: {url[:120]}')
        return 'url("")'

    def _import(match):
        if _keep(match.group('url').strip()):
            return match.group(0)
        print(f'[EXPORT] blocked css import: {match.group("url").strip()[:120]}')
        return ''

    html = _EXPORT_ATTR_URL_RE.sub(_attr, html)
    html = _EXPORT_CSS_URL_RE.sub(_css, html)
    html = _EXPORT_IMPORT_RE.sub(_import, html)
    return html


def _install_export_request_guard(page):
    """ISS-019: the export renders fully offline — abort any remote fetch a
    hostile slide may still carry. Only the declared font hosts pass."""
    def _guard(route):
        try:
            url = route.request.url or ''
            host = urlparse(url).hostname or ''
        except Exception:
            url, host = '', ''
        if url.lower().startswith(('http://', 'https://')) \
                and host.lower() not in _EXPORT_REMOTE_HOSTS:
            print(f'[EXPORT] blocked remote request: {url[:120]}')
            try:
                return route.abort()
            except Exception:
                return None
        try:
            return route.continue_()
        except Exception:
            return None
    try:
        page.route('**/*', _guard)
    except Exception:
        pass


def _default_tenant_logo_uri():
    """The logo /tenant-assets/<id>/logo serves when the tenant never uploaded
    one — the export should render the same image the live route sends."""
    p = BASE_DIR / 'assets' / 'logo.png'
    return p.as_uri() if p.is_file() else None


def _heal_section_divider_backgrounds(slides, cover_uri):
    if not cover_uri:
        return list(slides or [])
    healed = []
    for slide in slides or []:
        source = str(slide or '')
        is_divider = (
            'data-section-divider-background' in source
            or 'section_divider' in source
            or ('linear-gradient(160deg' in source and 'font-size:58px' in source)
        )
        healed.append(_force_section_divider_background(source, cover_uri) if is_divider else source)
    return healed


def generate_pdf(slides_html, branding=None, out_path=None, tenant_id=None):
    global LAST_PDF_ENGINE
    LAST_PDF_ENGINE = ''
    if not out_path:
        raise ValueError("out_path is required")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(slides_html, list):
        html = "\n".join(str(s) for s in slides_html)
    else:
        html = str(slides_html)

    print("[PDF] engine=python")
    print(f"[PDF] Generating PDF: {out_path.name}")

    # Resolve tenant logo placeholders and broken paths
    tenant_id = tenant_id or (branding or {}).get('tenant_id')
    html = resolve_logo_in_html(html, tenant_id)
    html = _strip_hidden_watermark_overlays(html)
    html = _resolve_project_file_urls(html, tenant_id)

    # Convert branding image routes to real file URIs so offline Playwright
    # rendering preserves both the company logo and its separate watermark.
    def _local_tenant_image_uri(tid, base_name):
        if not tid:
            return None
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            p = BASE_DIR / 'uploads' / str(tid) / f'{base_name}{ext}'
            if p.exists():
                return p.as_uri()
        return None

    logo_uri = _local_tenant_image_uri(tenant_id, 'logo') or _default_tenant_logo_uri()
    if logo_uri:
        html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/logo(?:\?[^\s"\'\\)]+)?', logo_uri, html)
    watermark_uri = _local_tenant_image_uri(tenant_id, 'watermark')
    if watermark_uri:
        html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/watermark(?:\?[^\s"\'\\)]+)?', watermark_uri, html)

    # Resolve relative asset URLs so Playwright can load local images/fonts
    html = _resolve_asset_urls(html)

    # ISS-019: after resolution, every resource must still be a data: URI or a
    # file under this tenant's allowed roots — the slide HTML is stored user
    # input and can smuggle file://, remote or traversal references.
    html = _sanitize_export_resource_urls(html, tenant_id)

    # Discover the actual cover image even when one or more logo tags precede it.
    cover_uri = _cover_image_url_from_html(html)
    if not cover_uri and tenant_id:
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            cp = BASE_DIR / 'uploads' / str(tenant_id) / 'creative' / f'cover{ext}'
            if cp.exists():
                cover_uri = cp.as_uri()
                break
    if cover_uri:
        for cover_pat in [r'#*IMAGE_COVER#*', r'#*COVER_IMAGE#*', r'#*MAIN_IMAGE#*', r'#*PROJECT_IMAGE_COVER#*']:
            html = re.sub(cover_pat, cover_uri, html, flags=re.IGNORECASE)

    # A home for fitted image copies (cleaned with the preview dir below).
    tmp_dir = tempfile.mkdtemp(prefix='pdf_preview_')
    tmp_root = Path(tmp_dir).resolve()

    # Downscale oversized images before extraction so the single print, the
    # chunked documents and the fallback all render the fitted copies while
    # the stored originals stay untouched.
    html = fit_export_images_in_html(html, tmp_root)

    # Strip any previously-baked font-family declarations so the tenant font wins
    html = sanitize_slide_html_for_export(html)
    slide_tags = len(re.findall(r'<div\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\1', html, re.I))
    slides = extract_slide_elements(html)
    if slides:
        slides = [_unwrap_spurious_map_summary_cards(slide) for slide in slides]
    if cover_uri and slides:
        slides = _heal_section_divider_backgrounds(slides, cover_uri)
    if slides:
        html = "\n".join(f'<div class="pdf-export-page">{slide}</div>' for slide in slides)
    if slide_tags and len(slides) != slide_tags:
        # Losing a slide between the deck and the file is exactly the failure that shipped a
        # 24-page PDF for a 49-slide deck, so it is stated loudly instead of being joined over.
        print(f"[PDF] WARNING: {slide_tags} slide elements in the html but {len(slides)} extracted")
    print(f"[PDF] slides to print: {len(slides)}")

    # Build tenant font CSS and layout/print CSS
    font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
    # A slide carrying `position:absolute` or `float` can leave the flow, and an inline declaration
    # with !important beats the export stylesheet. Pagination therefore belongs to a generated page
    # wrapper outside the slide: its fixed size and break remain in flow even when the slide itself
    # does not.
    layout_css = """
@page { size: 1280px 720px; margin: 0; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { margin:0 !important; padding:0 !important; width:1280px !important; height:720px !important; overflow:hidden !important; }
.pdf-export-page, .slide { width:1280px !important; height:720px !important; direction:rtl; position:relative !important; overflow:hidden !important; margin:0 !important; padding:0 !important; }
img { max-width:100%; max-height:100%; object-fit:contain; }
svg[data-chart], svg.combo-chart { max-width:100% !important; max-height:320px !important; height:auto !important; display:block; }
@media print {
    @page { size: 1280px 720px; margin: 0; }
    body#pdf-export-root { background:white !important; margin:0 !important; padding:0 !important; width:1280px !important; height:auto !important; display:block !important; columns:auto !important; column-count:auto !important; column-width:auto !important; grid-template-columns:none !important; grid-template-rows:none !important; gap:0 !important; overflow:visible !important; -webkit-print-color-adjust:exact !important; print-color-adjust:exact !important; }
    body#pdf-export-root > .pdf-export-page { margin:0 !important; border:none !important; page-break-after:always !important; break-after:page !important; page-break-inside:avoid !important; break-inside:avoid !important; width:1280px !important; height:720px !important; box-shadow:none !important; position:relative !important; display:block !important; float:none !important; inset:auto !important; transform:none !important; zoom:1 !important; overflow:hidden !important; }
    body#pdf-export-root > .pdf-export-page:last-of-type { page-break-after:auto !important; break-after:auto !important; }
    body#pdf-export-root > .pdf-export-page > .slide { margin:0 !important; border:none !important; width:1280px !important; height:720px !important; box-shadow:none !important; position:relative !important; display:block !important; float:none !important; inset:auto !important; transform:none !important; zoom:1 !important; }
    .slide [style*="columns"], .slide [style*="column-count"], .slide [data-site-analysis-text], .slide [data-map-summary-card] {
        break-inside: avoid !important;
        page-break-inside: avoid !important;
        column-fill: balance !important;
    }
    .slide .col, .slide [style*="columns"] > *, .slide [style*="column-count"] > * {
        break-inside: avoid !important;
        page-break-inside: avoid !important;
    }
}
"""

    # Wrap slide fragments and place the final font CSS just before </body> so it overrides everything
    if "<html" not in html.lower():
        html = f"""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<style>{layout_css}</style>
</head>
<body id="pdf-export-root" style="margin:0;padding:0;background:#fff;">{html}<style>{font_css}</style></body>
</html>"""
    else:
        if "</head>" in html:
            html = html.replace("</head>", f"<style>{layout_css}</style></head>", 1)
        if "</body>" in html:
            html = html.replace("</body>", f"<style>{font_css}</style></body>", 1)
        else:
            html = html + f"<style>{font_css}</style>"

    # The preview HTML lives in the same temporary directory.
    resolved_html_path = tmp_root / 'preview.html'
    if resolved_html_path.parent != tmp_root:
        raise RuntimeError('Invalid preview html path')
    print(f"[PDF] Writing resolved HTML to {resolved_html_path}...")
    with open(resolved_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    layout_report = []
    chromium_pdf_written = False
    try:
        from playwright.sync_api import sync_playwright
        print("[PDF] Launching Playwright...")
        with sync_playwright() as p:
            chunk_size = _print_chunk_size(len(slides))
            if slides and chunk_size and len(slides) > chunk_size:
                # Long image-heavy decks peak small-host limits in one print;
                # groups keep memory flat. The finally below still cleans up.
                produced, layout_report = _generate_pdf_chunked(
                    p, slides, layout_css, font_css, out_path, tmp_root)
                chromium_pdf_written = True
                LAST_PDF_ENGINE = 'chromium-chunked'
                print("[PDF] Generation complete!")
                print(f"[PDF] engine={LAST_PDF_ENGINE}")
                _verify_pdf_page_count(produced, len(slides), layout_report)
                return produced
            browser, launch_how = _launch_chromium(p)
            print(f"[PDF] Chromium ready via {launch_how}")
            page = browser.new_page()
            _install_export_request_guard(page)
            page.set_viewport_size({"width": 1280, "height": 720})

            file_url = resolved_html_path.as_uri()
            print(f"[PDF] Loading {file_url}...")
            page.goto(file_url, wait_until="load", timeout=30000)

            # Wait for fonts and images to load before printing
            print("[PDF] Waiting for fonts and images...")
            try:
                page.evaluate("() => document.fonts.ready")
                page.wait_for_function(
                    "() => Array.from(document.images).every(i => i.complete)",
                    timeout=30000
                )
                first_family = font_family.split(',')[0].strip().strip("\"'")
                font_probe = 'ابتثجحخدذرزسشصضطظعغفقكلمنهوي ABCxyz 0123456789'
                loaded = page.evaluate(
                    """async ({family, probe}) => {
                        const loaded = [];
                        for (const weight of [100, 300, 400, 500, 700, 900]) {
                            try {
                                const faces = await document.fonts.load(`${weight} 16px \"${family}\"`, probe);
                                loaded.push(...faces.map(face => ({weight: face.weight, status: face.status})));
                            } catch (error) {}
                        }
                        await document.fonts.ready;
                        return {
                            loaded,
                            checked: document.fonts.check(`400 16px \"${family}\"`, probe),
                            entries: Array.from(document.fonts).map(face => ({
                                family: face.family,
                                weight: face.weight,
                                status: face.status,
                            })),
                        };
                    }""",
                    {"family": first_family, "probe": font_probe},
                )
                print(f"[FONT] loaded '{first_family}': {loaded['checked']} ({len(loaded['loaded'])} faces)")
            except Exception:
                # Don't fail export because an image hung; print what we have.
                pass

            # Measure the printed layout before printing. A slide that is out of flow, hidden or
            # not one page tall shares a page with its neighbour, and the page count alone cannot
            # say which slide did it.
            try:
                page.emulate_media(media='print')
                layout_report = page.evaluate(
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
                layout_report = []

            # Generate the PDF
            print(f"[PDF] Printing to {out_path.name}...")
            page.pdf(
                path=str(out_path),
                width="1280px",
                height="720px",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
            )
            chromium_pdf_written = True
            isolated = False
            if slides and _pdf_page_count(out_path) < len(slides):
                print('[PDF] Chromium produced a short deck; printing isolated Chromium pages.')
                _generate_pdf_pages_with_playwright(page, slides, layout_css, font_css, out_path, tmp_dir)
                isolated = True
            browser.close()
        print("[PDF] Generation complete!")
        produced = str(out_path)
        LAST_PDF_ENGINE = 'chromium-isolated' if isolated else 'chromium'
        print(f"[PDF] engine={LAST_PDF_ENGINE}")
    except Exception as e:
        if chromium_pdf_written:
            print(f"[PDF] Isolated Chromium recovery failed ({e}); refusing a degraded PyMuPDF file.")
            traceback.print_exc()
            raise
        print(f"[PDF] Playwright failed ({e}); falling back to PyMuPDF.")
        print("[PDF] WARNING: the PyMuPDF fallback keeps the page count but shifts every "
              "1280px slide right (white strip on the left, clipped content on the right). "
              "Fix the browser on this host instead of trusting this file: check "
              "playwright_install.log / .vision_status or set CHROMIUM_PATH.")
        traceback.print_exc()
        produced = _generate_pdf_with_fitz(html, out_path, slides, layout_css, font_css)
        layout_report = []
        LAST_PDF_ENGINE = 'fitz-fallback'
        print("[PDF] engine=fitz-fallback (degraded layout)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _verify_pdf_page_count(produced, len(slides), layout_report)
    return produced


def describe_slide_layout_faults(layout_report, page_height=720):
    """Name the slides that cannot own a printed page, and why."""
    faults = []
    for item in layout_report or []:
        if not isinstance(item, dict):
            continue
        reasons = []
        if str(item.get('position')) in ('absolute', 'fixed'):
            reasons.append(f"position:{item.get('position')}")
        if str(item.get('display')) == 'none':
            reasons.append('display:none')
        if str(item.get('cssFloat')) in ('left', 'right'):
            reasons.append(f"float:{item.get('cssFloat')}")
        height = item.get('height')
        if isinstance(height, (int, float)) and abs(height - page_height) > 2:
            reasons.append(f"height:{int(height)}px")
        if reasons:
            faults.append(f"الشريحة {item.get('index')} ({'، '.join(reasons)})")
    return faults


def _verify_pdf_page_count(pdf_path, expected_slides, layout_report=None):
    """Refuse to hand back a PDF with fewer pages than the deck has slides.

    A missing slide used to reach the reader as a finished file: the export answered success and
    the PDF simply ended early. A short file is a failed export, not a smaller export — and the
    error names the slides whose printed layout cannot hold a page of their own.
    """
    if not pdf_path or not expected_slides:
        return
    try:
        import fitz
        with fitz.open(str(pdf_path)) as document:
            pages = document.page_count
    except Exception as error:
        print(f"[PDF] page count check skipped: {error}")
        return
    faults = describe_slide_layout_faults(layout_report)
    log_message = (f"[PDF] pages={pages} slides={expected_slides}"
                   + (f" faults={len(faults)}: {'; '.join(faults[:20])}" if faults else ''))
    try:
        print(log_message)
    except UnicodeEncodeError:
        print(log_message.encode('ascii', errors='backslashreplace').decode('ascii'))
    if pages < expected_slides:
        detail = (' الشرائح التي لا تشغل صفحة كاملة: ' + '، '.join(faults[:12])) if faults else ''
        raise RuntimeError(
            f'تعذر تصدير العرض كاملاً: الملف يحتوي {pages} صفحة مقابل {expected_slides} شريحة.{detail}')
    if pages > expected_slides:
        print(f"[PDF] WARNING: {pages} pages for {expected_slides} slides — a slide overflowed its page")



# Why the last snapshot failed. The reason used to exist only as a print, so a host where the
# editor works blind reported nothing more useful than "no image".
LAST_VISION_ERROR = ''


def render_slide_to_image_base64(slide_html, branding=None, tenant_id=None, width=1280, height=720):
    """
    Render a single slide HTML into a base64 PNG data URI via Playwright Chromium.
    Used for Vision-guided AI slide editing so multimodal models (Sol) can visually inspect layout.
    """
    global LAST_VISION_ERROR
    LAST_VISION_ERROR = ''
    if not slide_html or not isinstance(slide_html, str):
        LAST_VISION_ERROR = 'no slide html supplied'
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        LAST_VISION_ERROR = f'playwright package is not importable: {exc}'
        print("[VISION] Playwright not available; skipping vision snapshot")
        return None

    import base64
    tmp_dir = tempfile.mkdtemp(prefix='slide_vision_')
    try:
        tenant_id = tenant_id or (branding or {}).get('tenant_id')
        html = resolve_logo_in_html(slide_html, tenant_id)
        html = _strip_hidden_watermark_overlays(html)

        def _local_tenant_image_uri(tid, base_name):
            if not tid:
                return None
            for ext in ('.png', '.jpg', '.jpeg', '.webp'):
                p = BASE_DIR / 'uploads' / str(tid) / f'{base_name}{ext}'
                if p.exists():
                    return p.as_uri()
            return None

        logo_uri = _local_tenant_image_uri(tenant_id, 'logo') or _default_tenant_logo_uri()
        if logo_uri and tenant_id:
            html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/logo(?:\?[^\s"\'\\)]+)?', logo_uri, html)
        watermark_uri = _local_tenant_image_uri(tenant_id, 'watermark')
        if watermark_uri and tenant_id:
            html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/watermark(?:\?[^\s"\'\\)]+)?', watermark_uri, html)

        html = _resolve_project_file_urls(html, tenant_id)
        html = _resolve_asset_urls(html)
        html = _sanitize_export_resource_urls(html, tenant_id)
        html = sanitize_slide_html_for_export(html)
        slides = extract_slide_elements(html)
        if slides:
            slides = [_unwrap_spurious_map_summary_cards(slide) for slide in slides]
            html = slides[0]

        font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
        layout_css = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ margin:0; padding:0; background:#fff; direction:rtl; width:{width}px; height:{height}px; overflow:hidden; }}
.slide {{ width:{width}px !important; height:{height}px !important; direction:rtl; position:relative; overflow:hidden; }}
img {{ max-width:100%; max-height:100%; object-fit:contain; }}
svg[data-chart], svg.combo-chart {{ max-width:100% !important; max-height:320px !important; height:auto !important; display:block; }}
@media print {{
    .slide [style*="columns"], .slide [style*="column-count"], .slide [data-site-analysis-text], .slide [data-map-summary-card] {{
        break-inside: avoid !important;
        page-break-inside: avoid !important;
        column-fill: balance !important;
    }}
    .slide .col, .slide [style*="columns"] > *, .slide [style*="column-count"] > * {{
        break-inside: avoid !important;
        page-break-inside: avoid !important;
    }}
}}
"""

        full_html = f"""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<style>{layout_css}</style>
<style>{font_css}</style>
</head>
<body style="margin:0;padding:0;background:#fff;">
{html}
</body>
</html>"""

        slide_root = Path(tmp_dir).resolve()
        resolved_html_path = slide_root / 'slide_preview.html'
        if resolved_html_path.parent != slide_root:
            raise RuntimeError('Invalid slide preview path')
        with open(resolved_html_path, "w", encoding="utf-8") as f:
            f.write(full_html)

        with sync_playwright() as p:
            browser, _launch_how = _launch_chromium(p)
            page = browser.new_page(viewport={"width": width, "height": height})
            _install_export_request_guard(page)
            page.goto(resolved_html_path.as_uri(), wait_until="load", timeout=15000)
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            buf = page.screenshot(type='png')
            browser.close()
            return f"data:image/png;base64,{base64.b64encode(buf).decode('utf-8')}"
    except Exception as e:
        LAST_VISION_ERROR = f'{type(e).__name__}: {e}'
        print(f"[VISION ERROR] Playwright snapshot failed ({e}); trying PyMuPDF fallback")
        try:
            import fitz
            fitz_vision_css = f"""
@page {{ size: {width}px {height}px; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body, #pdf-export-root {{ margin: 0 !important; padding: 0 !important; width: {width}px !important; height: {height}px !important; overflow: hidden !important; background: #fff; direction: rtl; }}
.slide {{ width: {width}px !important; height: {height}px !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important; position: relative !important; display: block !important; }}
img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
"""
            fitz_doc_html = f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="utf-8"><style>{fitz_vision_css}</style><style>{font_css}</style></head><body style="margin:0;padding:0;background:#fff;">{html}</body></html>"""
            src = fitz.open('html', fitz_doc_html.encode('utf-8'), width=width, height=height)
            pdf_bytes = src.convert_to_pdf()
            src.close()
            with fitz.open('pdf', pdf_bytes) as doc:
                pix = doc[0].get_pixmap()
                png_bytes = pix.tobytes('png')
            print("[VISION] Rendered slide snapshot via PyMuPDF fallback")
            return f"data:image/png;base64,{base64.b64encode(png_bytes).decode('utf-8')}"
        except Exception as fe:
            print(f"[VISION ERROR] PyMuPDF vision fallback failed: {fe}")
            return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    generate_pdf(["<div class='slide'>test</div>"], {}, "outputs/test.pdf")
