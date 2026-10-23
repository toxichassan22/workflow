"""Build a fully editable PPTX from the Chromium-measured display lists."""

import os
import re
import time

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches


class Ctx:
    def __init__(self, branding, tenant_id, font_name):
        self.branding = branding or {}
        self.tenant_id = tenant_id
        self.font_name = font_name
        self.texts = []
        self.missing_images = []
        self.missing = []
        self.rasterized = []


def _norm(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _expected_texts(display):
    out = []
    for item in display.get('items') or []:
        kind = item.get('type')
        if kind in ('text', 'svg-text'):
            if _norm(item.get('text')):
                out.append(item['text'])
        elif kind == 'table':
            for row in item.get('rows') or []:
                for cell in row.get('cells') or []:
                    if _norm(cell.get('text')):
                        out.append(cell['text'])
    return out


def _verify_no_lost_text(display, rendered_texts, slide_number):
    expected = _expected_texts(display)
    if not expected:
        return
    rendered = _norm(' '.join(rendered_texts))
    missing = []
    for text in expected:
        needle = _norm(text)
        if needle and needle not in rendered:
            missing.append(needle)
    if missing:
        sample = ' | '.join(missing[:3])
        raise RuntimeError(
            f'تعذر تصدير الشريحة {slide_number} كاملة: نص مفقود ({sample})')


def _set_slide_background(slide):
    try:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    except Exception:
        pass


def _paint_item(slide, item, ctx):
    kind = item.get('type')
    if kind == 'box':
        return paint_box(slide, item, ctx)
    if kind == 'image':
        return paint_image(slide, item, ctx)
    if kind == 'text':
        return paint_text(slide, item, ctx)
    if kind == 'table':
        return paint_table(slide, item, ctx)
    if kind == 'svg-rect':
        return paint_svg_rect(slide, item, ctx)
    if kind == 'svg-ellipse':
        return paint_svg_ellipse(slide, item, ctx)
    if kind == 'svg-line':
        return paint_svg_line(slide, item, ctx)
    if kind == 'svg-polyline':
        return paint_svg_polyline(slide, item, ctx)
    if kind == 'svg-text':
        return paint_svg_text(slide, item, ctx)
    if kind == 'raster':
        return paint_raster(slide, item, ctx)
    return 0


def _render_display_list(slide, display, ctx, slide_number):
    if display.get('raster'):
        ctx.rasterized.append((slide_number, display.get('raster_reason') or 'raster'))
        paint_raster(slide, {'raster': display['raster']}, ctx)
        return
    for item in display.get('items') or []:
        try:
            _paint_item(slide, item, ctx)
        except Exception as exc:
            raise RuntimeError(
                f'تعذر تصدير الشريحة {slide_number} ({item.get("type")}): {exc}') from exc


def _verify_pptx_slide_count(output_path, expected):
    """Refuse to hand back a PPTX with fewer slides than the deck holds."""
    try:
        written = len(Presentation(output_path).slides)
    except Exception as exc:
        raise RuntimeError(f'تعذر التحقق من ملف PPTX: {exc}')
    print(f"[PPTX] slides={written} expected={expected}")
    try:
        print(f"[PPTX] file={os.path.basename(str(output_path))}")
    except UnicodeEncodeError:
        print(os.path.basename(str(output_path)).encode(
            'ascii', errors='backslashreplace').decode('ascii'))
    if written < expected:
        raise RuntimeError(
            f'تعذر تصدير العرض كاملاً: الملف يحتوي {written} شريحة مقابل {expected} شريحة.')
    return written


def generate_pptx(slides_data, project_name, branding=None, output_dir=None,
                  tenant_id=None):
    """Generate an editable PPTX that follows the rendered slide design.

    Every slide is measured by Chromium at 1280x720 (the same engine that
    produces the PDF), then rebuilt as native PowerPoint text boxes, tables,
    pictures and shapes at the measured coordinates. Nothing is re-flowed.
    """
    if not slides_data:
        raise ValueError('slides_data is required for PPTX export')
    if output_dir is None:
        output_dir = os.path.join(REPO_ROOT, 'outputs')
    os.makedirs(output_dir, exist_ok=True)

    branding = dict(branding or {})
    tenant_id = tenant_id or branding.get('tenant_id')
    font_name = _resolve_font_name(branding)
    ctx = Ctx(branding, tenant_id, font_name)

    print(f"[PPTX] Measuring {len(slides_data)} slides in Chromium...")
    display_lists = measure_slides(slides_data, branding, tenant_id)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for index, display in enumerate(display_lists):
        slide = prs.slides.add_slide(blank)
        _set_slide_background(slide)
        before = len(ctx.texts)
        before_images = len(ctx.missing_images)
        _render_display_list(slide, display, ctx, index + 1)
        if not display.get('raster'):
            _verify_no_lost_text(display, ctx.texts[before:], index + 1)
            new_missing = [src for src in ctx.missing_images[before_images:]
                           if src and not str(src).lower().startswith(('http://', 'https://', '//'))]
            if new_missing:
                raise RuntimeError(
                    f'تعذر تصدير الشريحة {index + 1}: صورة غير موجودة '
                    f'({str(new_missing[0])[:120]})')
        if (index + 1) % 5 == 0 or (index + 1) == len(display_lists):
            print(f"[PPTX] built {index + 1}/{len(display_lists)} slides")

    embed_fonts(prs, ctx)

    safe_name = ''.join(ch for ch in str(project_name or '')
                        if ch.isalnum() or ch in '-_ ')[:50].strip() or 'presentation'
    output_path = os.path.join(output_dir, f"{safe_name}_{int(time.time())}.pptx")
    prs.save(output_path)
    _verify_pptx_slide_count(output_path, len(slides_data))
    if ctx.rasterized:
        summary = ', '.join(f'{number}:{reason}' for number, reason in ctx.rasterized[:6])
        print(f"[PPTX] WARNING rasterized slides (not editable): {summary}")
    print(f"[PPTX] text lines={len(ctx.texts)}")
    return output_path
