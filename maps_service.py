"""
Google Maps service for generating map images and location data.
Uses direct HTTP requests to Google Maps APIs.
"""

import sys
import os
import json
import math
import uuid
import time
import requests
import re
import hashlib
import shutil
import threading
from urllib.parse import urlparse, urlsplit, urljoin, urlencode

# Force UTF-8 stdout so Arabic/unicode OSM tag names don't crash on Windows cp1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from datetime import datetime
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont

GOOGLE_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'uploads', 'maps')

# Every provider fetch in this module talks to exactly these hosts. The guard
# below keeps a malformed link or a future edit from turning any request sink
# into an SSRF entry point toward the intranet or cloud metadata.
_ALLOWED_REMOTE_HOSTS = (
    'maps.googleapis.com',
    'places.googleapis.com',
    'roads.googleapis.com',
    'overpass-api.de',
    'lz4.overpass-api.de',
    'overpass.kumi.systems',
    'google.com',
    'goo.gl',
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew past 30k lines, so its body lives in ordered
# files under maps_service_parts/, exec'd into this module's own namespace. Globals,
# monkeypatching (patch.object(maps_service, 'name')) and tracebacks are unchanged:
# part files are compiled with their real path so frames point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maps_service_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
