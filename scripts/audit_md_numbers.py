# -*- coding: utf-8 -*-
"""Cross-check numbers in transcribed md vs raw PDF text — refined."""
import re, sys, io
import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
AR = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
NUM = re.compile(r'[0-9٠-٩]+(?:[.,،][0-9٠-٩]+)*')
FOOTER = re.compile(r'ص\s*[0-9٠-٩]+\s*من\s*[0-9٠-٩]+|^\s*---\s*صفحة.*$|شكل\s*رقم')

def stems(text):
    out = set()
    for tok in NUM.findall(text):
        n = tok.translate(AR).split(',')[0].split('.')[0].lstrip('0') or '0'
        out.add(n)
    return out

def md_pages(path):
    raw = open(path, encoding='utf-8').read()
    blocks = re.split(r'---\s*صفحة\s*([0-9٠-٩]+)\s*---', raw)
    for i in range(1, len(blocks) - 1, 2):
        yield int(blocks[i].translate(AR)), blocks[i + 1]

JOBS = [
    ('docs/pdf/اشتراطات1.pdf',
     ['modules/platform/regulation_transcriptions/clean_1_50.md',
      'modules/platform/regulation_transcriptions/clean_51_100.md',
      'modules/platform/regulation_transcriptions/clean_101_151.md',
      'modules/platform/regulation_transcriptions/clean_151_200.md']),
    ('docs/pdf/اشتراطات2.pdf',
     ['modules/platform/regulation_transcriptions/clean2_1_142.md']),
]

for pdf_name, md_files in JOBS:
    doc = fitz.open(pdf_name)
    print(f'===== {pdf_name} =====')
    for md in md_files:
        for page_no, md_text in md_pages(md):
            if not (1 <= page_no <= len(doc)):
                continue
            raw_text = doc[page_no - 1].get_text()
            raw_stems = stems(raw_text)
            body_lines, figure_lines = [], []
            for line in md_text.splitlines():
                line = line.strip()
                if not line or FOOTER.search(line):
                    continue
                (figure_lines if line.startswith('شكل') else body_lines).append(line)
            body_extra = stems('\n'.join(body_lines)) - raw_stems
            fig_extra = stems('\n'.join(figure_lines)) - raw_stems
            body_extra = {n for n in body_extra if not (n.isdigit() and int(n) < 40)}
            fig_extra = {n for n in fig_extra if not (n.isdigit() and int(n) < 40)}
            if body_extra or fig_extra:
                print(f'p{page_no}: BODY={sorted(body_extra, key=lambda x: (len(x), x))} '
                      f'FIG={sorted(fig_extra, key=lambda x: (len(x), x))}')
    doc.close()
