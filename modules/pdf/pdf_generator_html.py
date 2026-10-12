"""
PDF Design Engine — HTML/CSS based using Playwright (Chromium).
Proper Arabic text rendering with full bidi support.
"""

import os
import re
import base64
from pathlib import Path
# Repo root anchor — path constants were written when this module sat at the
# repo root; they resolve from here so the file can live under modules/<domain>/.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(REPO_ROOT, 'app.py')) and os.path.dirname(REPO_ROOT) != REPO_ROOT:
    REPO_ROOT = os.path.dirname(REPO_ROOT)

PROJECT_ROOT = Path(REPO_ROOT)


PAGE_W_PT = 960
PAGE_H_PT = 540
PAGE_W_IN = 13.333
PAGE_H_IN = 7.5

FONT_DIR = str(PROJECT_ROOT / 'assets' / 'fonts')
_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under pdf_generator_html_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(pdf_generator_html, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pdf_generator_html_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside pdf_generator_html_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
