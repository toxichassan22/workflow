"""Deterministic reliability helpers for the presentation designer chat.

The AI planner may choose an action, but these helpers make two user-visible
operations deterministic: adding stored image descriptions and paginating
large tables without dropping or duplicating rows.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import math
import re
import concurrent.futures
import copy
import json
import os
import threading
import time
import uuid
from functools import wraps
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Sequence, Tuple, Union
from urllib.parse import unquote, urlsplit


SplitParts = Union[int, str]
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SRC_RE = re.compile(r"\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_TABLE_RE = re.compile(r"<table\b[^>]*>[\s\S]*?</table>", re.IGNORECASE)
_TBODY_RE = re.compile(r"(<tbody\b[^>]*>)([\s\S]*?)(</tbody>)", re.IGNORECASE)
_TR_RE = re.compile(r"<tr\b[^>]*>[\s\S]*?</tr>", re.IGNORECASE)
_TD_RE = re.compile(r"<(?:td|th)\b[^>]*>[\s\S]*?</(?:td|th)>", re.IGNORECASE)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under designer_chat_reliability_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(designer_chat_reliability, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'designer_chat_reliability_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside designer_chat_reliability_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
