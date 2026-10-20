# -*- coding: utf-8 -*-
"""Audit v2: Arabic literals in backend Python that can reach the UI."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AR = re.compile(r'[؀-ۿ]')
STR_RE = re.compile(
    r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|"
    r"'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"")

UI_KEY_RE = re.compile(
    r"['\"](?:error|message|detail|hint|label|title|name|status|note|reason|"
    r"text|empty|empty_state|subtitle|badge|cta|warning|description|field|"
    r"tab|section|toast|heading|button|btn|action|step|state|placeholder|"
    r"emptyText|empty_text|header|caption|statusLabel|decision_note|"
    r"required|optional|approved|rejected|pending|failed|suggestion|item|"
    r"points|issue|issues|check|checks|missing|errors?|fail|ok|success_msg)['\"]"
    r"\s*:\s*$", re.I)
UI_INLINE_RE = re.compile(
    r"['\"](?:error|message|detail|hint|label|title|status|warning|"
    r"decision_note|suggestion|item|detail)['\"]\s*:\s*$", re.I)
PROMPT_CTX_RE = re.compile(
    r"(messages\s*=\s*\[|['\"]role['\"]\s*:|_prompt|PROMPT|system_prompt|"
    r"user_prompt|build_.*prompt|instructions?_)", re.I)

GROUPS = [
    ('api', re.compile(r'app_parts|app\.py|auth\.py')),
    ('db', re.compile(r'db_parts|db\.py')),
    ('deck', re.compile(r'slide_engine|pdf_generator|design_templates|'
                       r'executive_content|exports')),
    ('market', re.compile(r'market_study|regulation_digest|population')),
    ('designer', re.compile(r'designer_')),
    ('maps', re.compile(r'maps_service')),
    ('changes', re.compile(r'change_tracking')),
    ('genpdf', re.compile(r'generate_pdf_from_preview')),
]


def group_of(path):
    s = str(path)
    for name, rx in GROUPS:
        if rx.search(s):
            return name
    return 'other'


def load_covered():
    src = '\n'.join(p.read_text(encoding='utf-8')
                    for p in sorted((ROOT / 'assets' / 'i18n').glob('*.js')))
    merged = {}
    for block in re.findall(
            r'/\*I18N_EN_AUTO_BEGIN\*/(.*?)/\*I18N_EN_AUTO_END\*/', src, re.S):
        merged.update(json.loads(block))
    for lang in ('AR', 'EN'):
        m = re.search(r'/\*I18N_%s_BEGIN\*/(.*?)/\*I18N_%s_END\*/' % (lang, lang),
                      src, re.S)
        if m:
            for v in json.loads(m.group(1)).values():
                merged.setdefault(v, v)
    return {re.sub(r'\s+', ' ', k).strip() for k in merged}


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def scan_file(path):
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return []
    spans = [(m.start(), m.end(), m.group(0)) for m in STR_RE.finditer(text)]
    out = []
    for i, (s0, s1, lit) in enumerate(spans):
        body = lit[3:-3] if lit[:3] in ("'''", '"""') else lit[1:-1]
        if not AR.search(body):
            continue
        # skip if nested inside a bigger literal (prompt JSON examples etc.)
        nested = any(o0 < s0 and s1 <= o1 for j, (o0, o1, _)
                     in enumerate(spans) if j != i)
        if nested:
            continue
        line = text.count('\n', 0, s0) + 1
        before = text[max(0, s0 - 200):s0]
        last_line = before.split('\n')[-1]
        nlit = norm(body)
        dynamic = '{' in body or '}' in body or '\\' in body
        cls = 'OTHER'
        if UI_KEY_RE.search(last_line) or UI_INLINE_RE.search(last_line):
            cls = 'UI'
        elif PROMPT_CTX_RE.search(before):
            cls = 'PROMPT'
        out.append(dict(file=str(path.relative_to(ROOT)), line=line,
                        cls=cls, lit=nlit, dyn=dynamic,
                        ctx=norm(before[-120:] + ' <LIT> ' +
                                 text[s1:s1 + 60].split('\n')[0])))
    return out


def main():
    files = []
    for p in ROOT.rglob('*.py'):
        s = str(p)
        if any(x in s for x in ('.venv', 'node_modules', '__pycache__',
                                'sandbox', 'tests', 'tmp')):
            continue
        if p.name.startswith(('test_', 'verify_', 'db_head_check',
                              'audit_', 'build_qa_doc', 'seed_sample',
                              'run_regeneration', 'rel_', 'i18n_audit')):
            continue
        files.append(p)
    rows = []
    for f in files:
        rows.extend(scan_file(f))
    covered = load_covered()
    Path('i18n_audit_rows.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print('total literals:', len(rows))
    print(Counter(r['cls'] for r in rows))
    print(Counter(group_of(r['file']) for r in rows))
    # uncovered UI by group
    unc = [r for r in rows if r['cls'] == 'UI' and r['lit'] not in covered
           and len(r['lit']) > 2]
    print('\nUNCOVERED UI by group:', Counter(group_of(r['file']) for r in unc))
    byfile = Counter(r['file'] for r in unc)
    for k, v in byfile.most_common(30):
        print(v, k)


if __name__ == '__main__':
    main()
