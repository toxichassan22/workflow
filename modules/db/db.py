"""
Database layer for Multi-Tenant SaaS.
SQLite-based with full migration support.
"""

import os
import re
import uuid
import json
import hashlib
from datetime import datetime, timedelta, timezone
from flask import g

import db_driver as sqlite3

# Repo root anchor — path constants were written when this module sat at the
# repo root; they resolve from here so the file can live under modules/<domain>/.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(REPO_ROOT, 'app.py')) and os.path.dirname(REPO_ROOT) != REPO_ROOT:
    REPO_ROOT = os.path.dirname(REPO_ROOT)

DB_PATH = (
    os.environ.get('DB_PATH')
    or os.environ.get('DATABASE_URL')
    or os.path.join(REPO_ROOT, 'app.db')
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew past 30k lines, so its body lives in ordered
# files under db_parts/, exec'd into this module's own namespace. Globals,
# monkeypatching (patch.object(db, 'name')) and tracebacks are unchanged:
# part files are compiled with their real path so frames point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside db_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR
