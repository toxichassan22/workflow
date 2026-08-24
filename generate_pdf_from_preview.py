import json
import os
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from design_templates import build_font_css, extract_slide_elements, sanitize_slide_html_for_export
from slide_engine import resolve_logo_in_html

BASE_DIR = Path(__file__).resolve().parent


def _generate_pdf_with_fitz(html, out_path):
    """Pure-Python fallback using PyMuPDF when Playwright is unavailable."""
    print("[FONT] WARNING: PyMuPDF fallback cannot render @font-face/base64 fonts; custom font may not apply")
    import fitz
    # Render HTML to a 1280x720 pt page; may not be pixel-perfect but avoids 502s.
    src = fitz.open('html', html.encode('utf-8'), width=1280, height=720)
    src.save(out_path)
    return str(out_path)


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


def generate_pdf(slides_html, branding=None, out_path=None, tenant_id=None):
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

    # Convert the logo reference to an actual file URI so Playwright can render it
    def _local_logo_uri(tid):
        if not tid:
            return None
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            p = BASE_DIR / 'uploads' / str(tid) / f'logo{ext}'
            if p.exists():
                return p.as_uri()
        return None

    logo_uri = _local_logo_uri(tenant_id)
    if logo_uri:
        # Replace /tenant-assets/<tenant>/logo?... with the real file URI
        html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/logo(?:\?[^\s"\'\\)]+)?', logo_uri, html)

    # Resolve relative asset URLs so Playwright can load local images/fonts
    html = _resolve_asset_urls(html)

    # Strip any previously-baked font-family declarations so the tenant font wins
    html = sanitize_slide_html_for_export(html)
    slide_tags = len(re.findall(r'<div\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\1', html, re.I))
    slides = extract_slide_elements(html)
    if slides:
        html = "\n".join(slides)
    if slide_tags and len(slides) != slide_tags:
        # Losing a slide between the deck and the file is exactly the failure that shipped a
        # 24-page PDF for a 49-slide deck, so it is stated loudly instead of being joined over.
        print(f"[PDF] WARNING: {slide_tags} slide elements in the html but {len(slides)} extracted")
    print(f"[PDF] slides to print: {len(slides)}")

    # Build tenant font CSS and layout/print CSS
    font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
    layout_css = """
* { margin:0; padding:0; box-sizing:border-box; }
.slide { width:1280px; height:720px; direction:rtl; position:relative; overflow:hidden; }
img { max-width:100%; max-height:100%; object-fit:cover; }
@media print {
    body { background:white !important; margin:0 !important; padding:0 !important; -webkit-print-color-adjust:exact !important; print-color-adjust:exact !important; }
    .slide { margin:0 !important; border:none !important; page-break-after:always !important; page-break-inside:avoid !important; width:1280px !important; height:720px !important; box-shadow:none !important; }
    .slide:last-child { page-break-after:auto !important; }
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
<body style="margin:0;padding:0;background:#fff;">{html}<style>{font_css}</style></body>
</html>"""
    else:
        if "</head>" in html:
            html = html.replace("</head>", f"<style>{layout_css}</style></head>", 1)
        if "</body>" in html:
            html = html.replace("</body>", f"<style>{font_css}</style></body>", 1)
        else:
            html = html + f"<style>{font_css}</style>"

    # Use a temporary directory for the preview HTML so it is cleaned up automatically
    tmp_dir = tempfile.mkdtemp(prefix='pdf_preview_')
    resolved_html_path = Path(tmp_dir) / 'preview.html'
    print(f"[PDF] Writing resolved HTML to {resolved_html_path}...")
    with open(resolved_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        from playwright.sync_api import sync_playwright
        print("[PDF] Launching Playwright...")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--font-render-hinting=none"
                ]
            )
            page = browser.new_page()
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

            # Generate the PDF
            print(f"[PDF] Printing to {out_path.name}...")
            page.pdf(
                path=str(out_path),
                width="1280px",
                height="720px",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
            )
            browser.close()
        print("[PDF] Generation complete!")
        produced = str(out_path)
    except Exception as e:
        print(f"[PDF] Playwright failed ({e}); falling back to PyMuPDF.")
        traceback.print_exc()
        produced = _generate_pdf_with_fitz(html, out_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _verify_pdf_page_count(produced, len(slides))
    return produced


def _verify_pdf_page_count(pdf_path, expected_slides):
    """Refuse to hand back a PDF with fewer pages than the deck has slides.

    A missing slide used to reach the reader as a finished file: the export answered success and
    the PDF simply ended early. A short file is a failed export, not a smaller export.
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
    print(f"[PDF] pages={pages} slides={expected_slides}")
    if pages < expected_slides:
        raise RuntimeError(
            f'تعذر تصدير العرض كاملاً: الملف يحتوي {pages} صفحة مقابل {expected_slides} شريحة.')
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

        def _local_logo_uri(tid):
            if not tid:
                return None
            for ext in ('.png', '.jpg', '.jpeg', '.webp'):
                p = BASE_DIR / 'uploads' / str(tid) / f'logo{ext}'
                if p.exists():
                    return p.as_uri()
            return None

        logo_uri = _local_logo_uri(tenant_id)
        if logo_uri and tenant_id:
            html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id)) + r'/logo(?:\?[^\s"\'\\)]+)?', logo_uri, html)

        html = _resolve_asset_urls(html)
        html = sanitize_slide_html_for_export(html)
        slides = extract_slide_elements(html)
        if slides:
            html = slides[0]

        font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
        layout_css = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ margin:0; padding:0; background:#fff; direction:rtl; width:{width}px; height:{height}px; overflow:hidden; }}
.slide {{ width:{width}px !important; height:{height}px !important; direction:rtl; position:relative; overflow:hidden; }}
img {{ max-width:100%; max-height:100%; object-fit:cover; }}
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

        resolved_html_path = Path(tmp_dir) / 'slide_preview.html'
        with open(resolved_html_path, "w", encoding="utf-8") as f:
            f.write(full_html)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--font-render-hinting=none"
                ]
            )
            page = browser.new_page(viewport={"width": width, "height": height})
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
        print(f"[VISION ERROR] Failed to render slide snapshot: {e}")
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    generate_pdf(["<div class='slide'>test</div>"], {}, "outputs/test.pdf")

