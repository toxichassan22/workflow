"""Shared primitives for the browser-measured PPTX builder.

Every value here maps a CSS measurement (already resolved by Chromium) onto a
native PowerPoint object. Nothing in this file re-implements CSS layout.
"""

import base64
import math
import os
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

# 96 dpi mapping: 1280px -> 13.333in, 720px -> 7.5in
EMU_PER_PX = 914400 / 96
SLIDE_W_PX, SLIDE_H_PX = 1280, 720

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_REPO_ROOT, 'app.py')) \
        and os.path.dirname(_REPO_ROOT) != _REPO_ROOT:
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
BASE_DIR = Path(_REPO_ROOT)

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

_RGB_RE = re.compile(r'rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)'
                     r'(?:[,\s/]+([\d.]+%?))?\s*\)', re.I)
_HEX_RE = re.compile(r'#([0-9a-fA-F]{3,8})')


def _strip_icons(value):
    return _ICON_RE.sub('', str(value or '')).replace('\u2022', '').strip()


def _px_to_emu(px):
    return Emu(int(round(float(px) * EMU_PER_PX)))


def _px_to_pt(px):
    return Pt(max(1.0, float(px) * 0.75))


def _hex_to_rgb(hex_color):
    value = str(hex_color or '').lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    if len(value) >= 8:
        value = value[:6]
    if len(value) != 6:
        raise ValueError(value)
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _alpha_pct_from_token(token):
    """CSS alpha token -> PowerPoint transparency percent (0 solid .. 100 clear)."""
    token = str(token or '').strip()
    if not token:
        return None
    try:
        alpha = float(token[:-1]) / 100.0 if token.endswith('%') else float(token)
    except ValueError:
        return None
    alpha = max(0.0, min(1.0, alpha))
    return None if alpha >= 0.999 else (1.0 - alpha) * 100.0


def _css_color(value):
    """CSS color string -> (RGBColor|None, transparency pct|None)."""
    text = str(value or '').strip().lower()
    if not text or text in ('transparent', 'none', 'inherit', 'initial', 'unset'):
        return None, None
    if text == 'white':
        return RGBColor(0xFF, 0xFF, 0xFF), None
    if text == 'black':
        return RGBColor(0, 0, 0), None
    match = _RGB_RE.search(text)
    if match:
        try:
            rgb = RGBColor(int(float(match.group(1))), int(float(match.group(2))),
                           int(float(match.group(3))))
        except ValueError:
            return None, None
        return rgb, _alpha_pct_from_token(match.group(4))
    match = _HEX_RE.search(text)
    if match:
        raw = match.group(1)
        try:
            if len(raw) == 3:
                raw = ''.join(ch * 2 for ch in raw)
            rgb = _hex_to_rgb(raw[:6])
        except ValueError:
            return None, None
        alpha = None
        if len(raw) == 8:
            alpha = (1.0 - int(raw[6:8], 16) / 255.0) * 100.0
        return rgb, alpha
    return None, None


def _parse_px(value, default=None):
    match = re.search(r'(-?[\d.]+)\s*(px|pt|in|cm|mm|%)?', str(value or '').strip().lower())
    if not match:
        return default
    number, unit = float(match.group(1)), (match.group(2) or 'px')
    if unit == 'px':
        return number
    if unit == 'pt':
        return number * 96.0 / 72.0
    if unit == 'in':
        return number * 96.0
    if unit == 'cm':
        return number * 96.0 / 2.54
    if unit == 'mm':
        return number * 96.0 / 25.4
    return default


def _parse_radius(value):
    """border-radius shorthand -> one px radius (0 when absent)."""
    text = str(value or '').strip()
    if not text:
        return 0.0
    first = text.split('/')[0].split()[0]
    if first.endswith('%'):
        return -1.0  # percentage marker, resolved against the box later
    return _parse_px(first, 0.0) or 0.0


def _set_shape_fill(shape, rgb, alpha_pct=None):
    if rgb is None:
        try:
            shape.fill.background()
        except Exception:
            pass
        return
    try:
        shape.fill.solid()
        shape.fill.fore_color.rgb = rgb
        if alpha_pct:
            solid = shape.fill._xPr.find(qn('a:solidFill'))
            if solid is not None:
                clr = solid.find(qn('a:srgbClr'))
                if clr is not None:
                    alpha = clr.makeelement(
                        qn('a:alpha'), {'val': str(int((100 - alpha_pct) * 1000))})
                    clr.append(alpha)
    except Exception:
        pass


def _set_shape_gradient(shape, gradient):
    """Apply a measured CSS gradient (N stops, alpha, angle/radial) to a shape."""
    stops = (gradient or {}).get('stops') or []
    if not stops:
        return False
    try:
        spPr = shape._element.spPr
        for tag in ('a:noFill', 'a:solidFill', 'a:gradFill', 'a:blipFill',
                    'a:pattFill', 'a:grpFill'):
            existing = spPr.find(qn(tag))
            if existing is not None:
                spPr.remove(existing)
        grad = spPr.makeelement(qn('a:gradFill'), {'rotWithShape': '1'})
        gs_list = grad.makeelement(qn('a:gsLst'), {})
        for stop in stops:
            try:
                offset = max(0.0, min(1.0, float(stop.get('offset') or 0.0)))
            except (TypeError, ValueError):
                offset = 0.0
            gs = gs_list.makeelement(qn('a:gs'), {'pos': str(int(offset * 100000))})
            rgb, alpha = _css_color(stop.get('color'))
            if rgb is None:
                # CSS `transparent` stop (the cover veil fades to nothing).
                rgb, alpha = RGBColor(0, 0, 0), 100.0
            clr = gs.makeelement(qn('a:srgbClr'), {'val': str(rgb)})
            if alpha:
                clr.append(clr.makeelement(
                    qn('a:alpha'), {'val': str(int((100 - alpha) * 1000))}))
            gs.append(clr)
            gs_list.append(gs)
        grad.append(gs_list)
        if str(gradient.get('type') or 'linear') == 'radial':
            path = grad.makeelement(qn('a:path'), {'path': 'circle'})
            path.append(path.makeelement(qn('a:fillToRect'), {
                'l': '50000', 't': '50000', 'r': '50000', 'b': '50000'}))
            grad.append(path)
        else:
            angle = float(gradient.get('angle') or 0.0)
            grad.append(grad.makeelement(qn('a:lin'), {
                'ang': str(int(angle * 60000)), 'scaled': '1'}))
        geometry = spPr.find(qn('a:prstGeom'))
        if geometry is None:
            geometry = spPr.find(qn('a:custGeom'))
        if geometry is not None:
            geometry.addnext(grad)
        else:
            spPr.insert(0, grad)
        return True
    except Exception:
        return False


def _set_shape_line(shape, rgb, width_px, dash=None, alpha_pct=None):
    if rgb is None or (width_px is not None and width_px <= 0):
        try:
            shape.line.fill.background()
        except Exception:
            pass
        return
    try:
        shape.line.color.rgb = rgb
        if width_px:
            shape.line.width = Pt(max(0.25, float(width_px) * 0.75))
        if dash:
            dash_map = {
                'dashed': MSO_LINE_DASH_STYLE.DASH,
                'dotted': MSO_LINE_DASH_STYLE.ROUND_DOT,
                'dash-dot': MSO_LINE_DASH_STYLE.DASH_DOT,
                'longdash': MSO_LINE_DASH_STYLE.LONG_DASH,
            }
            style = dash_map.get(str(dash).lower())
            if style is not None:
                shape.line.dash_style = style
    except Exception:
        pass


def _no_line(shape):
    try:
        shape.line.fill.background()
    except Exception:
        pass


def _set_shape_alpha(shape, alpha_pct):
    """Shape-wide transparency for fills and lines."""
    if not alpha_pct:
        return
    try:
        solid = shape.fill._xPr.find(qn('a:solidFill'))
        if solid is None:
            return
        clr = solid.find(qn('a:srgbClr'))
        if clr is None:
            return
        if clr.find(qn('a:alpha')) is None:
            clr.append(clr.makeelement(
                qn('a:alpha'), {'val': str(int((100 - alpha_pct) * 1000))}))
    except Exception:
        pass


def _apply_radius(shape, width_px, height_px, radius_px):
    """Rounded-rectangle geometry from a measured corner radius."""
    if not radius_px:
        return
    small = max(1.0, min(width_px, height_px))
    if radius_px < 0:
        # percentage radius: 50% of the small side is a pill/circle
        radius_px = small / 2.0
    try:
        if radius_px >= small / 2.0 - 0.5:
            shape.adjustments[0] = 0.5
        else:
            shape.adjustments[0] = max(0.0, min(0.5, radius_px / small))
    except Exception:
        pass


def _shape_for_rect(slide, x, y, w, h, radius_px):
    small = max(1.0, min(w, h))
    if radius_px < 0:
        shape_type = MSO_SHAPE.OVAL if small > 0 else MSO_SHAPE.RECTANGLE
    else:
        shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius_px else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, _px_to_emu(x), _px_to_emu(y),
                                   _px_to_emu(max(w, 0.1)), _px_to_emu(max(h, 0.1)))
    _strip_theme_style(shape)
    if shape_type == MSO_SHAPE.ROUNDED_RECTANGLE:
        _apply_radius(shape, w, h, radius_px)
    return shape


def _strip_theme_style(shape):
    """Drop the theme shape style (it carries an unwanted drop shadow)."""
    try:
        style = shape._element.find(qn('p:style'))
        if style is not None:
            shape._element.remove(style)
    except Exception:
        pass


def _set_picture_alpha(picture, alpha_pct):
    if not alpha_pct:
        return
    try:
        blip = picture._element.blipFill.find(qn('a:blip'))
        if blip is None:
            return
        if blip.find(qn('a:alphaModFix')) is not None:
            return
        blip.append(blip.makeelement(
            qn('a:alphaModFix'), {'amt': str(int((100 - alpha_pct) * 1000))}))
    except Exception:
        pass


def _picture_shape(picture, width_px, height_px, radius_px):
    """Clip a picture to a rounded rectangle (or circle) of its own size."""
    if not radius_px:
        return
    try:
        spPr = picture._element.spPr
        prst = spPr.find(qn('a:prstGeom'))
        if prst is None:
            return
        small = max(1.0, min(width_px, height_px))
        if radius_px < 0 or radius_px >= small / 2.0 - 0.5:
            prst.set('prst', 'ellipse')
            for child in list(prst):
                prst.remove(child)
            prst.append(prst.makeelement(qn('a:avLst'), {}))
            return
        prst.set('prst', 'roundRect')
        for child in list(prst):
            prst.remove(child)
        av = prst.makeelement(qn('a:avLst'), {})
        gd = av.makeelement(qn('a:gd'), {
            'name': 'adj',
            'fmla': 'val %d' % int(round(max(0.0, min(50000, radius_px / small * 100000)))),
        })
        av.append(gd)
        prst.append(av)
    except Exception:
        pass


def _add_outer_shadow(shape, shadow):
    """CSS box-shadow -> DrawingML outer shadow."""
    if not shadow:
        return
    try:
        x = float(shadow.get('x') or 0.0)
        y = float(shadow.get('y') or 0.0)
        blur = max(0.0, float(shadow.get('blur') or 0.0))
        rgb, alpha = _css_color(shadow.get('color'))
        rgb = rgb or RGBColor(0, 0, 0)
        alpha = 40.0 if alpha is None else max(alpha, 5.0)
        dist = math.hypot(x, y)
        angle = (math.degrees(math.atan2(y, x)) + 90.0) % 360.0 if dist else 0.0
        spPr = shape._element.spPr
        effect_lst = spPr.find(qn('a:effectLst'))
        if effect_lst is None:
            effect_lst = spPr.makeelement(qn('a:effectLst'), {})
            spPr.append(effect_lst)
        shdw = effect_lst.makeelement(qn('a:outerShdw'), {
            'blurRad': str(int(blur * EMU_PER_PX)),
            'dist': str(int(dist * EMU_PER_PX)),
            'dir': str(int(angle * 60000)),
            'algn': 'ctr',
            'rotWithShape': '0',
        })
        clr = shdw.makeelement(qn('a:srgbClr'), {
            'val': str(rgb)})
        clr.append(clr.makeelement(
            qn('a:alpha'), {'val': str(int((100 - alpha) * 1000))}))
        shdw.append(clr)
        effect_lst.append(shdw)
    except Exception:
        pass


def _image_size(data):
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as image:
            return image.size
    except Exception:
        return (1280, 720)


def _resolve_image_bytes(src, tenant_id=None):
    """Resolve a slide image reference to bytes without following remote URLs."""
    if not src:
        return None
    src = str(src).strip().strip('"\'')
    if not src or '##' in src:
        return None
    try:
        if src.lower().startswith('data:image'):
            header, _, payload = src.partition(',')
            if ';base64' in header and payload:
                return base64.b64decode(payload)
            return None
        parsed = urlparse(src)
        if parsed.scheme in ('http', 'https') or src.startswith('//'):
            return None
        if parsed.scheme and parsed.scheme != 'file':
            return None
        candidates = []
        if parsed.scheme == 'file':
            from generate_pdf_from_preview import _export_url_to_local_path
            candidates.append(_export_url_to_local_path(src))
        else:
            rel = src.split('?')[0].split('#')[0].lstrip('/')
            is_tenant_asset = rel.startswith('tenant-assets/')
            if is_tenant_asset:
                rel = 'uploads/' + rel[len('tenant-assets/'):]
            candidates.append(BASE_DIR / rel)
            if is_tenant_asset and not Path(rel).suffix:
                candidates += [Path(str(BASE_DIR / rel) + ext)
                               for ext in ('.png', '.jpg', '.jpeg', '.webp')]
            if tenant_id and '/' not in rel:
                candidates += [BASE_DIR / 'uploads' / str(tenant_id) / (rel + ext if ext else rel)
                               for ext in ('', '.png', '.jpg', '.jpeg', '.webp')]
        from generate_pdf_from_preview import _export_allowed_local_path
        for candidate in candidates:
            try:
                if candidate.is_file() and _export_allowed_local_path(
                        candidate, tenant_id, base_dir=BASE_DIR):
                    return candidate.read_bytes()
            except OSError:
                continue
        return None
    except Exception:
        return None


def _image_bytes(src, tenant_id=None):
    data = _resolve_image_bytes(src, tenant_id)
    if not data:
        return None
    try:
        from generate_pdf_from_preview import fit_image_bytes
        return fit_image_bytes(data)
    except Exception:
        return data


def _resolve_font_name(branding):
    raw = str((branding or {}).get('font_family') or '').strip()
    if raw:
        first = raw.split(',')[0].strip().strip('"\'')
        low = first.lower()
        if first and 'tenant-managed' not in low and 'platform-fallback' not in low \
                and 'tenant-font' not in low:
            return first
    return 'IBM Plex Sans Arabic'


def _run_alpha(run, alpha_pct):
    if not alpha_pct:
        return
    try:
        solid = run._r.get_or_add_rPr().find(qn('a:solidFill'))
        if solid is None:
            return
        clr = solid.find(qn('a:srgbClr'))
        if clr is None:
            return
        if clr.find(qn('a:alpha')) is None:
            clr.append(clr.makeelement(
                qn('a:alpha'), {'val': str(int((100 - alpha_pct) * 1000))}))
    except Exception:
        pass


def _spacing_hundredths(px):
    try:
        return int(round(float(px) * 0.75 * 100))
    except (TypeError, ValueError):
        return 0
