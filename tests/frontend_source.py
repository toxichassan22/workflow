"""The SPA shell exactly as the server assembles it.

index.html is a loader: it carries the document chrome and one placeholder, and
the body markup lives in ordered index_parts/*.html files. Literal-source
assertions must read the assembled shell, never the loader alone, or they stop
seeing the markup without failing.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL_PATH = ROOT / 'index.html'
PARTS_DIR = ROOT / 'index_parts'
ORDERS_PATH = ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py'
PARTS_MARKER = '<!--__INDEX_PARTS__-->\n'


def parts_order():
    source = ORDERS_PATH.read_text(encoding='utf-8')
    match = re.search(r'INDEX_PARTS_ORDER\s*=\s*\(([\s\S]*?)\)', source)
    if not match:
        raise AssertionError('INDEX_PARTS_ORDER is missing from 22f_frontend_bundles.py')
    return tuple(re.findall(r"'([^']+)'", match.group(1)))


def shell_text():
    skeleton = SHELL_PATH.read_text(encoding='utf-8')
    if skeleton.count(PARTS_MARKER) != 1:
        raise AssertionError('index.html must carry exactly one index-parts placeholder')
    return skeleton.replace(
        PARTS_MARKER,
        ''.join((PARTS_DIR / name).read_text(encoding='utf-8') for name in parts_order()),
    )
