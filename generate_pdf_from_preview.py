import json
import os
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from urllib.parse import unquote, urlparse
from design_templates import build_font_css, extract_slide_elements, sanitize_slide_html_for_export
from slide_engine import (
    _cover_image_url_from_html,
    _force_section_divider_background,
    _unwrap_spurious_map_summary_cards,
    resolve_logo_in_html,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under generate_pdf_from_preview_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(generate_pdf_from_preview, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_pdf_from_preview_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
