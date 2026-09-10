#!/usr/bin/env python3
"""Report what makes an exported deck PDF/PPTX heavy (stdlib + app deps only).

Usage:
    python3 scripts/analyze_export_size.py <file.pdf|file.pptx> [more files...]

For PDFs it lists every embedded image (pages using it, pixel size, bytes)
via PyMuPDF, flagging duplicates by content hash. For PPTX it lists
ppt/media/* parts with sizes and duplicate groups. Use it on a real export
to decide whether the weight is duplicate images, oversized photos, fonts,
or slide count itself.
"""

import hashlib
import os
import sys
import zipfile


def _mb(num):
    return f'{num / 1048576:.2f} MB'


def analyze_pdf(path):
    import fitz
    size = os.path.getsize(path)
    doc = fitz.open(path)
    try:
        images = {}  # xref -> dict
        for page_no in range(doc.page_count):
            for img in doc.get_page_images(page_no, full=True):
                xref = img[0]
                entry = images.setdefault(xref, {'pages': [], 'info': None})
                entry['pages'].append(page_no + 1)
        total_image_bytes = 0
        rows = []
        for xref, entry in images.items():
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            data = info.get('image') or b''
            digest = hashlib.md5(data).hexdigest()[:10]
            total_image_bytes += len(data)
            rows.append({
                'pages': len(entry['pages']),
                'first_page': entry['pages'][0],
                'px': f"{info.get('w')}x{info.get('h')}",
                'ext': info.get('ext'),
                'bytes': len(data),
                'md5': digest,
            })
        rows.sort(key=lambda row: -row['bytes'])
        print(f'{path}: {doc.page_count} pages, file {_mb(size)}')
        print(f'  embedded images: {len(rows)} refs, {_mb(total_image_bytes)} total bytes')
        digests = {}
        for row in rows:
            digests.setdefault(row['md5'], []).append(row['first_page'])
        dupes = {key: val for key, val in digests.items() if len(val) > 1}
        if dupes:
            print(f'  duplicate images by content: {len(dupes)} groups')
            for key, val in list(dupes.items())[:5]:
                print(f'    md5 {key} on pages {val[:10]}')
        print('  largest images:')
        for row in rows[:12]:
            print(f"    p{row['first_page']} x{row['pages']} {row['px']} {row['ext']} "
                  f"{_mb(row['bytes'])} md5:{row['md5']}")
        fonts = set()
        for page_no in range(doc.page_count):
            for font in doc.get_page_fonts(page_no, full=True):
                fonts.add((font[3], font[4] if len(font) > 4 else ''))
        print(f'  embedded font faces: {len(fonts)}')
        for name, kind in sorted(fonts)[:10]:
            print(f'    {name} ({kind})')
    finally:
        doc.close()


def analyze_pptx(path):
    size = os.path.getsize(path)
    with zipfile.ZipFile(path) as archive:
        media = [n for n in archive.namelist() if n.startswith('ppt/media/')]
        rows = []
        for name in media:
            data = archive.read(name)
            rows.append({
                'name': name.split('/')[-1],
                'bytes': len(data),
                'md5': hashlib.md5(data).hexdigest()[:10],
            })
        try:
            from pptx import Presentation
            slides = len(Presentation(path).slides)
        except Exception:
            slides = '?'
    total_media = sum(row['bytes'] for row in rows)
    rows.sort(key=lambda row: -row['bytes'])
    print(f'{path}: {slides} slides, file {_mb(size)}, media {_mb(total_media)} in {len(rows)} parts')
    digests = {}
    for row in rows:
        digests.setdefault(row['md5'], []).append(row['name'])
    dupes = {key: val for key, val in digests.items() if len(val) > 1}
    if dupes:
        print(f'  duplicate media by content: {len(dupes)} groups')
        for key, val in list(dupes.items())[:5]:
            print(f'    md5 {key}: {val[:6]}')
    else:
        print('  no duplicate media parts')
    print('  largest media:')
    for row in rows[:12]:
        print(f"    {row['name']} {_mb(row['bytes'])} md5:{row['md5']}")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        lower = path.lower()
        try:
            if lower.endswith('.pdf'):
                analyze_pdf(path)
            elif lower.endswith('.pptx'):
                analyze_pptx(path)
            else:
                print(f'skip (not pdf/pptx): {path}')
        except Exception as exc:
            print(f'FAILED {path}: {type(exc).__name__}: {exc}')
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
