import os
import re
import shutil
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from design_templates import build_font_css
from slide_engine import resolve_logo_in_html

BASE_DIR = Path(__file__).resolve().parent


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

    print(f"[PDF] Generating PDF: {out_path.name}")

    # Resolve tenant logo placeholders and broken paths
    html = resolve_logo_in_html(html, tenant_id or (branding or {}).get('tenant_id'))

    # Inject tenant font CSS and print styles
    font_css, font_family = build_font_css(branding or {}, tenant_id or (branding or {}).get('tenant_id'), embed=True)
    custom_style = f"""
{font_css}
    @media print {{
        body {{
            background: white !important;
            margin: 0 !important;
            padding: 0 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }}
        .slide {{
            margin: 0 !important;
            border: none !important;
            page-break-after: always !important;
            page-break-inside: avoid !important;
            width: 1280px !important;
            height: 720px !important;
            box-shadow: none !important;
        }}
        .slide:last-child {{
            page-break-after: auto !important;
        }}
    }}
    """

    # Inject the style block before </head>
    if "</head>" in html:
        html = html.replace("</head>", f"<style>{custom_style}</style></head>")
    else:
        html = html + f"<style>{custom_style}</style>"

    # Resolve relative asset URLs so Playwright can load local images/fonts
    html = _resolve_asset_urls(html)

    # Wrap slide fragments in a minimal HTML document if needed
    if "<html" not in html.lower():
        html = f"""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<style>{custom_style}</style>
</head>
<body style="margin:0;padding:0;background:#fff;">{html}</body>
</html>"""

    # Use a temporary directory for the preview HTML so it is cleaned up automatically
    tmp_dir = tempfile.mkdtemp(prefix='pdf_preview_')
    resolved_html_path = Path(tmp_dir) / 'preview.html'
    print(f"[PDF] Writing resolved HTML to {resolved_html_path}...")
    with open(resolved_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    try:
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
            page.goto(file_url, wait_until="networkidle")

            # Wait for fonts and images to load before printing
            print("[PDF] Waiting for fonts and images...")
            page.evaluate("() => document.fonts.ready")
            page.wait_for_function(
                "() => Array.from(document.images).every(i => i.complete)",
                timeout=120000
            )

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
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[PDF] Generation complete!")
    return str(out_path)


if __name__ == "__main__":
    generate_pdf(["<div class='slide'>test</div>"], {}, "outputs/test.pdf")
