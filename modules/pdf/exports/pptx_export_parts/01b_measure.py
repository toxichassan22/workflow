"""Chromium measurement session for the PPTX builder.

The PDF is pixel-accurate because Chromium lays the slide out. The PPTX export
now reads the same layout instead of guessing it: each slide is loaded at
1280x720 with the export font CSS, and a collector walks the rendered DOM and
returns every visible paint item with absolute coordinates, computed styles,
table geometry and SVG primitives.
"""

import base64
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import design_templates
import generate_pdf_from_preview
from design_templates import build_font_css, extract_slide_elements, sanitize_slide_html_for_export
from slide_engine import _unwrap_spurious_map_summary_cards, resolve_logo_in_html

_MEASURE_EXPORT_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html, body {
    margin:0; padding:0; background:#fff; direction:rtl;
    width:1280px; height:720px; overflow:hidden;
}
.slide {
    width:1280px !important; height:720px !important; direction:rtl;
    position:relative; overflow:hidden;
}
img { max-width:100%; max-height:100%; object-fit:contain; }
svg[data-chart], svg.combo-chart {
    max-width:100% !important; max-height:320px !important;
    height:auto !important; display:block;
}
"""


def _local_tenant_image_uri(tenant_id, base_name):
    if not tenant_id:
        return None
    for ext in ('.png', '.jpg', '.jpeg', '.webp'):
        path = BASE_DIR / 'uploads' / str(tenant_id) / f'{base_name}{ext}'
        if path.exists():
            return path.as_uri()
    return None


def _default_tenant_logo_uri():
    path = BASE_DIR / 'assets' / 'logo.png'
    return path.as_uri() if path.is_file() else None


def _prepare_slide_for_measurement(slide_html, branding, tenant_id):
    """The same preprocessing the PDF export applies to every slide."""
    tenant_id = tenant_id or (branding or {}).get('tenant_id')
    try:
        html = resolve_logo_in_html(slide_html, tenant_id)
    except Exception:
        # Direct exporter calls (tests, CLI) have no Flask app context; the
        # slide HTML already carries the logo it was saved with.
        html = slide_html
    html = generate_pdf_from_preview._strip_hidden_watermark_overlays(html)
    logo_uri = _local_tenant_image_uri(tenant_id, 'logo') or _default_tenant_logo_uri()
    if logo_uri and tenant_id:
        html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id))
                      + r'/logo(?:\?[^\s"\'\\)]+)?', logo_uri, html)
    watermark_uri = _local_tenant_image_uri(tenant_id, 'watermark')
    if watermark_uri and tenant_id:
        html = re.sub(r'/tenant-assets/' + re.escape(str(tenant_id))
                      + r'/watermark(?:\?[^\s"\'\\)]+)?', watermark_uri, html)
    try:
        html = generate_pdf_from_preview._resolve_project_file_urls(html, tenant_id)
    except Exception:
        pass
    html = generate_pdf_from_preview._resolve_asset_urls(html)
    html = generate_pdf_from_preview._sanitize_export_resource_urls(html, tenant_id)
    html = sanitize_slide_html_for_export(html)
    slides = extract_slide_elements(html)
    if slides:
        html = _unwrap_spurious_map_summary_cards(slides[0])
    return html


def _font_css_for(branding, tenant_id):
    try:
        return build_font_css(branding or {}, tenant_id, embed=True)
    except Exception as exc:
        print(f"[PPTX] font css unavailable ({type(exc).__name__}); using family name only")
        try:
            return build_font_css(branding or {}, tenant_id, family_only=True)
        except Exception:
            return '', 'IBM Plex Sans Arabic'


def _write_measurement_document(slide_html, branding, tenant_id, workdir, index):
    html = _prepare_slide_for_measurement(slide_html, branding, tenant_id)
    font_css, _family = _font_css_for(branding, tenant_id)
    document = f"""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<style>{_MEASURE_EXPORT_CSS}</style>
<style>{font_css or ''}</style>
</head>
<body>{html}</body>
</html>"""
    path = Path(workdir) / f'slide_{index:03d}.html'
    path.write_text(document, encoding='utf-8')
    return path




def _collect_slide(page):
    try:
        page.evaluate("() => document.fonts.ready")
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => Array.from(document.images).every(img => img.complete)",
            timeout=30000)
    except Exception:
        pass
    data = page.evaluate(_COLLECTOR_JS)
    if data.get('warnings'):
        unique = sorted(set(data['warnings']))
        print(f"[PPTX] unsupported css: {', '.join(unique)}")
    if data.get('raster'):
        # Safety net: preserve the visual, lose editability for that slide only.
        reason = data.get('raster')
        png = page.screenshot(type='png')
        data = {'raster': base64.b64encode(png).decode('ascii'),
                'raster_reason': reason, 'items': []}
    return data


def measure_slides(slides_data, branding=None, tenant_id=None):
    """Return one display list per slide, measured by Chromium at 1280x720."""
    if not slides_data:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(f'تعذر التصدير: Playwright غير متاح ({exc})')

    workdir = tempfile.mkdtemp(prefix='pptx_measure_')
    results = []
    try:
        with sync_playwright() as playwright:
            browser, how = generate_pdf_from_preview._launch_chromium(playwright)
            print(f"[PPTX] Chromium ready via {how}")
            page = browser.new_page(
                viewport={'width': SLIDE_W_PX, 'height': SLIDE_H_PX},
                device_scale_factor=2)
            generate_pdf_from_preview._install_export_request_guard(page)
            for index, raw in enumerate(slides_data):
                slide_data = dict(raw) if isinstance(raw, dict) else {'html': str(raw or '')}
                path = _write_measurement_document(
                    slide_data.get('html', ''), branding, tenant_id, workdir, index + 1)
                page.goto(path.as_uri(), wait_until='load', timeout=30000)
                display = _collect_slide(page)
                display['title'] = slide_data.get('title', '')
                display['type'] = slide_data.get('type', '')
                results.append(display)
                if (index + 1) % 5 == 0 or (index + 1) == len(slides_data):
                    print(f"[PPTX] measured {index + 1}/{len(slides_data)} slides")
            browser.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return results
