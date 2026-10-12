"""Identity, roles and security subsystems (t20-t23, d01, d07).

Covers per-user project scopes, last-company-admin protection, the d01 section
self-approval policy, the d07 client-approved admin access grant, the expanded
separation-of-duties matrix and extended invites. Runs against a temporary
SQLite database and never calls Google or an AI API.
"""

import os
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under test_identity_security_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(test_identity_security, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_identity_security_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside test_identity_security_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
