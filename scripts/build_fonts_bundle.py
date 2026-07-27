"""Generate fonts_bundle.json from the real font files in assets/fonts.

Run this locally after `git lfs pull` so the font files are real binary data,
not LFS pointers. The resulting fonts_bundle.json is committed to the repo and
read at runtime by the Python export engines.
"""
import base64
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

FONTS = [
    ('TheSansArabic-Light', 'assets/fonts/TheSansArabic-Light.otf', 'opentype'),
    ('TheSansArabic-Bold', 'assets/fonts/BahijTheSansArabic-Bold.ttf', 'truetype'),
]


def _is_lfs_pointer(path):
    try:
        if path.stat().st_size < 500:
            return True
        with open(path, 'rb') as f:
            return b'version https://git-lfs' in f.read(100)
    except Exception:
        return True


def build():
    result = {}
    for family, relpath, fmt in FONTS:
        path = BASE_DIR / relpath
        if not path.exists() or _is_lfs_pointer(path):
            raise RuntimeError(f'{relpath} is missing or an LFS pointer; run git lfs pull first')
        with open(path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('ascii')
        result[family] = {'family': family, 'format': fmt, 'data': data}

    out = BASE_DIR / 'fonts_bundle.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f)
    print(f'[fonts] wrote {out} with {len(result)} faces')


if __name__ == '__main__':
    build()
