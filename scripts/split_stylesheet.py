"""Split a CSS/JS bundle part into smaller ordered files at top-level
boundaries (brace depth 0 — never inside a rule, @media block or function).

Usage:
  python scripts/split_stylesheet.py <file> <new_name1> <new_name2> ... [--apply]

Splits the file into len(names) roughly equal chunks; each chunk keeps whole
rules/statements. Dry-run prints the proposed line ranges.
"""
import os, re, sys

sys.stdout.reconfigure(errors='replace')


def depth_zero_boundaries(lines):
    """Line indexes (1-based) where a new chunk may start: the previous line
    left brace depth at 0 and closed cleanly ('}' ';' '*/' or blank)."""
    depth = 0
    in_comment = False
    in_str = None
    cand = []
    for i, l in enumerate(lines):
        j = 0
        while j < len(l):
            c = l[j]
            if in_comment:
                e = l.find('*/', j)
                if e < 0:
                    j = len(l)
                    break
                in_comment = False
                j = e + 2
                continue
            if in_str:
                if c == '\\':
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
                j += 1
                continue
            if l[j:j + 2] == '/*':
                in_comment = True
                j += 2
                continue
            if l[j:j + 2] == '//':
                break
            if c in ('"', "'", '`'):
                in_str = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            j += 1
        if depth == 0 and not in_comment:
            s = l.strip()
            if s.endswith('}') or s.endswith(';') or s.endswith('*/') or s == '' or s.endswith('{'):
                cand.append(i + 2)  # next line is a valid chunk start
    return cand


JS_STMT = re.compile(r'^\s{4}(async\s+function|function|const|let|var|class)\b|^\s{4}//|^\s{4}/\*')


def node_parses(lines, tmpdir, tag):
    import subprocess, tempfile
    p = os.path.join(tmpdir, tag + '.js')
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.writelines(lines)
    r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
    return r.returncode == 0


def js_candidates(lines):
    """Statement-start lines (4-space base indent) — cheap pre-filter; each cut
    is confirmed with node --check on both halves before it is used."""
    return [i + 1 for i, l in enumerate(lines) if JS_STMT.match(l)]


def pick_js_cut(lines, tmpdir, want, used):
    raw = [c for c in js_candidates(lines) if c > used]
    for c in sorted(raw, key=lambda c: abs(c - want)):
        if node_parses(lines[:c - 1], tmpdir, 'a') and node_parses(lines[c - 1:], tmpdir, 'b'):
            return c
    raise SystemExit('no clean JS cut near line %d' % want)


def main():
    args = [a for a in sys.argv[2:] if a != '--apply']
    apply = '--apply' in sys.argv
    at = None
    names = []
    for a in args:
        if a.startswith('--at='):
            at = [int(x) for x in a[5:].split(',')]
        else:
            names.append(a)
    path = sys.argv[1]
    assert len(names) >= 2, 'need at least two output names'

    import tempfile
    with open(path, encoding='utf-8', newline='') as f:
        lines = f.readlines()

    tmpdir = tempfile.mkdtemp()
    is_js = path.endswith('.js')
    if not is_js:
        cand = depth_zero_boundaries(lines)
    total = len(lines)
    n = len(names)
    goal = total / n
    targets = at if at else [goal * k for k in range(1, n)]
    assert len(targets) == n - 1, '--at count must equal parts-1'
    cuts, used = [], 0
    for want in targets:
        if is_js:
            best = pick_js_cut(lines, tmpdir, want, used)
        else:
            best = min((c for c in cand if c > used), key=lambda c: abs(c - want))
        cuts.append(best)
        used = best

    ranges = []
    prev = 1
    for c in cuts:
        ranges.append((prev, c - 1))
        prev = c
    ranges.append((prev, total))

    print(f'{path}: {total} lines -> {len(names)} parts')
    for name, (s, e) in zip(names, ranges):
        snippet = next((l.strip()[:60] for l in lines[s - 1:e] if l.strip()), '')
        print(f'  {name:45s} {s:>6}-{e:<6} {e - s + 1:>5} lines  | {snippet}')
    if not apply:
        return
    d = os.path.dirname(path)
    for name, (s, e) in zip(names, ranges):
        out = os.path.join(d, name)
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        with open(out, 'w', encoding='utf-8', newline='') as f:
            f.writelines(lines[s - 1:e])
    # verify: parts concatenated == original
    body = []
    for name, _ in zip(names, ranges):
        out = os.path.join(d, name)
        body += open(out, encoding='utf-8', newline='').readlines()
    assert body == lines, 'LINE MISMATCH'
    os.remove(path)
    print('VERIFIED + removed original')


if __name__ == '__main__':
    main()
