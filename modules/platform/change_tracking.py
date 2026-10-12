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
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside change_tracking_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
