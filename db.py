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

DB_PATH = (
    os.environ.get('DB_PATH')
    or os.environ.get('DATABASE_URL')
    or os.path.join(os.path.dirname(__file__), 'app.db')
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew past 30k lines, so its body lives in ordered
# files under db_parts/, exec'd into this module's own namespace. Globals,
# monkeypatching (patch.object(db, 'name')) and tracebacks are unchanged:
# part files are compiled with their real path so frames point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
