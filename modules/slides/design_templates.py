"""
Design templates for Multi-Tenant SaaS.
Pre-built design styles that companies can choose from.
"""
import base64
import io
import json
import os
import re

# Repo root anchor — path constants were written when this module sat at the
# repo root; they resolve from here so the file can live under modules/<domain>/.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(REPO_ROOT, 'app.py')) and os.path.dirname(REPO_ROOT) != REPO_ROOT:
    REPO_ROOT = os.path.dirname(REPO_ROOT)

BASE_DIR = REPO_ROOT
FALLBACK_FONTS = "'IBM Plex Sans Arabic', Tahoma, Arial, sans-serif"


# The class attribute is read as a token list, never as a substring: `\bslide\b` also matches
# `slide-inner`, `slide-footer` and `slide-title`, because `-` is a word boundary. With the
# bounded reader below that chopped one real slide into three fragments — an empty
# `<div class="slide"></div>` plus its own inner blocks — so the export both miscounted the deck
# and printed it in pieces.
_SLIDE_OPEN_RE = re.compile(
    r'<div\b[^>]*\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\')[^>]*>',
    re.I,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under design_templates_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(design_templates, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'design_templates_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside design_templates_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
