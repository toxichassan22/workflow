"""
PPTX Export Engine — Tenant-aware, fully editable.

Every slide becomes native PowerPoint objects (text boxes, tables, pictures,
shapes) built from the slide HTML, so the downloaded file keeps the site's
design (colors, order, images, tables) and every text stays editable.

Pure Python: no Playwright/Chromium dependency, works on hosting too.
Slide size is 13.333 x 7.5 in (16:9), i.e. 1280x720 px at 96 dpi.
"""

import base64
import os
import re
import time
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor

from design_templates import (
    dark_surface_color,
    normalize_hex_color,
    readable_text_color,
    sanitize_slide_html_for_export,
)
from generate_pdf_from_preview import (
    _export_allowed_local_path,
    _export_url_to_local_path,
    _resolve_asset_urls,
    _resolve_project_file_urls,
    fit_image_bytes,
)
from slide_engine import resolve_logo_in_html

BASE_DIR = Path(__file__).resolve().parent.parent

# 96 dpi mapping: 1280px -> 13.333in, 720px -> 7.5in
EMU_PER_PX = 914400 / 96
SLIDE_W_PX, SLIDE_H_PX = 1280, 720

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under pptx_export_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(pptx_export, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pptx_export_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
