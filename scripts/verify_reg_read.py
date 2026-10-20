# -*- coding: utf-8 -*-
"""Offline+live verification of the regulation reading pipeline (no Flask request)."""
import _bootstrap  # noqa: F401  (repo-root sys.path wiring)
import sys, os, json, tempfile, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\workflow')

import db
_tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_tmp, 'verify.db')

import app as A

print('=== STEP 1: page index ===')
records = A._build_regulation_page_index()
for name in A.REGULATION_PDF_NAMES:
    recs = [r for r in records if r['name'] == name]
    tables = [r for r in recs if r['has_table']]
    print(f'{name}: {len(recs)} indexed pages, {len(tables)} pages with tables')
print('total records:', len(records))

print()
print('=== STEP 2: find villa setbacks page in اشتراطات1 ===')
hits = []
for r in records:
    if r['name'] != 'اشتراطات1.pdf':
        continue
    t = r['text']
    if ('الفيالت' in t or 'الفيلات' in t) and 'ارتداد' in t and 'جوار' in t:
        hits.append((r['page'], r['has_table'], len(t)))
print('candidate pages:', hits[:20])

print()
print('=== STEP 3: search evidence with villa site_facts ===')
site_facts = {
    'area_sqm': 600, 'zoning_code': 'س ف', 'land_use': 'سكني فلل',
    'city': 'جدة', 'project_type': 'فيلا سكنية', 'axis_type': '', 'building_type': 'فيلا',
}
pkg, warns = A.search_official_regulations_evidence('سكني فلل ارتدادات فيلا 600', site_facts)
for d in pkg['documents']:
    print(d['name'], 'text_pages:', len(d['text_pages']), 'table_pages:', len(d['table_pages']),
          'context_chars:', len(d['context']))
print('warnings:', warns)
# which pages mention villa setbacks?
villa_pages = [p for p, _, _ in hits]
for d in pkg['documents']:
    if d['name'] == 'اشتراطات1.pdf':
        inter = [p for p in villa_pages if p in d['text_pages']]
        print('villa setback pages included in text context:', inter)
        inter_t = [p for p in villa_pages if p in d['table_pages']]
        print('villa setback pages included in table pages:', inter_t)

print()
print('=== STEP 4: render candidate page to PNG for ground truth ===')
import fitz
target = hits[0][0] if hits else None
if target:
    doc = fitz.open(r'D:\workflow\اشتراطات1.pdf')
    page = doc[target - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
    out = os.path.join(_tmp, f'villa_p{target}.png')
    pix.save(out)
    print('saved:', out, pix.width, 'x', pix.height)
    # also check find_tables on that page
    try:
        tabs = page.find_tables().tables
        print('tables found on page:', len(tabs))
        for tb in tabs[:2]:
            ext = tb.extract()
            for row in ext[:12]:
                print(' | '.join('' if c is None else str(c).replace('\n', ' ') for c in row))
    except Exception as e:
        print('find_tables error:', e)
    doc.close()
