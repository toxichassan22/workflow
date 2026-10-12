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
# Repo root anchor — path constants were written when this module sat at the
# repo root; they resolve from here so the file can live under modules/<domain>/.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(REPO_ROOT, 'app.py')) and os.path.dirname(REPO_ROOT) != REPO_ROOT:
    REPO_ROOT = os.path.dirname(REPO_ROOT)

_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_pdf_from_preview_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside generate_pdf_from_preview_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
