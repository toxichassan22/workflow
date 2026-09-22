"""Turn two versions of a presentation or a project draft into readable Arabic change lines.

The history used to record one generic sentence — «تعديل المحتوى» — so a reader could not tell what
had changed, who had changed it, or whether a slide had lost content. Nothing compared two versions
anywhere in the codebase, and AI edits were not recorded at all.

Everything here is pure: it takes the old and the new value and returns lines. That keeps it
testable without a database, a request context, or a model.
"""

import difflib
import json
import os
import re

import db

# A slide carries markup, inline styles and placeholders. Only the parts a reader would call content
# are compared; a pure styling change is reported as such instead of as a text change.
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')
_STYLE_RE = re.compile(r'\sstyle\s*=\s*"[^"]*"', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'<img[^>]+src\s*=\s*"([^"]+)"', re.IGNORECASE)
_BG_URL_RE = re.compile(r'url\(\s*[\'"]?([^\'")]+)', re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r'##[A-Z0-9_]+##')
_WATERMARK_RE = re.compile(
    r'<div\b[^>]*\b(?:data-slide-watermark=["\']true["\']|class=["\'][^"\']*\bslide-watermark\b)[^>]*>',
    re.IGNORECASE,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under change_tracking_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(change_tracking, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'change_tracking_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
