"""Split a giant python module into ordered part files exec'd into the
module's own namespace (the same pattern assets/js uses for the frontend).

Usage:
  python scripts/split_module.py <file.py> <parts_dir> <header_end_line>
      [--cut LINE ...] [--target N] [--nparts N] [--name IDX=slug ...] [--apply]
  python scripts/split_module.py <file.py> <parts_dir> <header_end_line>
      --class CLASSNAME --nparts N [--apply]

Without --apply it only prints the proposed layout (dry run).

--class splits one giant class: non-test members stay on the class in the
loader file (as the base class, keeping its name), test_* methods are spread
over subclasses in the part files. unittest still discovers every subclass.
"""
import ast, os, re, sys

sys.stdout.reconfigure(errors='replace')


def top_blocks(lines):
    """(start,end) 1-based inclusive blocks: each top-level statement plus the
    blank/comment gap preceding it."""
    tree = ast.parse(''.join(lines))
    stmts = [(s.lineno, s.end_lineno) for s in tree.body]
    blocks, prev = [], 0
    for s, e in stmts:
        blocks.append((prev + 1, e))
        prev = e
    if prev < len(lines):
        blocks.append((prev + 1, len(lines)))
    return blocks


def first_banner(block_lines):
    for l in block_lines[:6]:
        if re.match(r'\s*#\s*[━─=]{3,}\s*$', l):
            continue
        m = re.match(r'\s*#\s*(.+)', l)
        if m and m.group(1).strip():
            return m.group(1).strip()
        if l.strip() and not l.strip().startswith('#'):
            break
    return None


def slugify(text, fallback):
    if text:
        s = re.sub(r'[^a-zA-Z0-9]+', '_', text.lower()).strip('_')[:40]
        if s:
            return s
    return fallback


def part_name(idx, block_lines, overrides):
    banner = first_banner(block_lines)
    firstroute = next((m for m in (re.search(r"@app\.route\('(/api/[^']+)'", l) for l in block_lines) if m), None)
    firstdef = next((m for m in (re.match(r'\s*(?:def|class)\s+(\w+)', l) for l in block_lines) if m), None)
    if firstroute:
        fb = firstroute.group(1).replace('/api/', '').replace('/', '_').replace('<', '').replace('>', '')
    elif firstdef:
        fb = firstdef.group(1).lstrip('_')
    else:
        fb = f'part{idx}'
    return f'{idx:02d}_{overrides.get(idx) or slugify(banner, fb)}.py'


def parse_args(argv):
    opts = {'cuts': set(), 'target': 2200, 'apply': '--apply' in argv,
            'overrides': {}, 'nparts': None, 'cls': None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--cut':
            i += 1
            while i < len(argv) and argv[i].isdigit():
                opts['cuts'].add(int(argv[i])); i += 1
            continue
        if a == '--target':
            opts['target'] = int(argv[i + 1]); i += 2; continue
        if a == '--nparts':
            opts['nparts'] = int(argv[i + 1]); i += 2; continue
        if a == '--class':
            opts['cls'] = argv[i + 1]; i += 2; continue
        if a == '--name':
            i += 1
            while i < len(argv) and '=' in argv[i]:
                k, v = argv[i].split('=', 1)
                opts['overrides'][int(k)] = v
                i += 1
            continue
        i += 1
    return opts


def loader_text(parts_dir, modname):
    leaf = os.path.basename(parts_dir.rstrip('/\\'))
    return f'''
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under {leaf}/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object({modname}, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '{leaf}')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
'''


def write_parts(parts_dir, names, ranges, lines):
    os.makedirs(parts_dir, exist_ok=True)
    for name, (s, e) in zip(names, ranges):
        with open(os.path.join(parts_dir, name), 'w', encoding='utf-8', newline='') as f:
            f.writelines(lines[s - 1:e])


def verify(path, parts_dir, names, header_lines, tail_lines, orig_lines):
    out = list(header_lines) + list(tail_lines)
    # remove the loader block itself for comparison: compare content-wise by
    # reconstructing = header + part bodies must equal original minus nothing
    body = []
    for name in names:
        with open(os.path.join(parts_dir, name), encoding='utf-8', newline='') as vf:
            body += vf.readlines()
    return out, body


def split_flat(path, parts_dir, header_end, opts, lines, blocks):
    starts = {b[0] for b in blocks}
    assert header_end in {b[1] for b in blocks}, f'header_end {header_end} not a statement boundary'

    real_cuts = set()
    for c in opts['cuts']:
        cand = max((s for s in starts if s <= c), default=None)
        if cand and cand > header_end:
            real_cuts.add(cand)

    hdr_idx = next(i for i, b in enumerate(blocks) if b[1] == header_end)
    rest = blocks[hdr_idx + 1:]

    if opts['nparts']:
        sizes = [e - s + 1 for s, e in rest]
        goal = sum(sizes) / opts['nparts']
        acc = 0
        for (s, e), sz in zip(rest, sizes):
            if acc >= goal * 0.8 and len(real_cuts) < opts['nparts'] - 1:
                real_cuts.add(s)
                acc = 0
            acc += sz

    parts, cur, cur_start = [], [], None

    def starts_with_banner(b):
        return any(re.match(r'\s*#\s*[━─=]{3,}', l) for l in lines[b[0] - 1:b[0] + 5])

    for b in rest:
        size = sum(e - s + 1 for s, e in cur)
        if cur and (b[0] in real_cuts or (size >= opts['target'] and starts_with_banner(b)) or size >= opts['target'] * 1.6):
            parts.append((cur_start, cur[-1][1]))
            cur, cur_start = [], None
        if cur_start is None:
            cur_start = b[0]
        cur.append(b)
    if cur:
        parts.append((cur_start, cur[-1][1]))
    return parts


def split_class(path, opts, lines, tree):
    """Split one giant TestCase class: loader keeps non-test members on the
    original class name; parts get subclasses with test_* methods."""
    cls = next(s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == opts['cls'])
    members = cls.body
    is_test = lambda m: isinstance(m, ast.FunctionDef) and m.name.startswith('test')
    base_members = [m for m in members if not is_test(m)]
    test_methods = [m for m in members if is_test(m)]

    # member slice = gap (comments/decorators above it) + the member itself;
    # computed over ALL members so gaps never swallow a sibling's lines
    all_blocks, prev = [], cls.lineno
    for m in members:
        all_blocks.append((prev + 1, m.end_lineno))
        prev = m.end_lineno
    base_blocks = [b for m, b in zip(members, all_blocks) if not is_test(m)]
    test_blocks = [b for m, b in zip(members, all_blocks) if is_test(m)]

    bases = ', '.join(ast.unparse(b) for b in cls.bases) or 'object'
    base_name = cls.name

    # class-def line (decorators live in the gap above cls.lineno already)
    class_line = f'class {base_name}({bases}):\n'
    if not base_members:
        base_body = '    pass\n'
    else:
        base_body = ''.join(''.join(lines[s - 1:e]) for s, e in base_blocks)

    # method chunks -> parts
    total = sum(e - s + 1 for s, e in test_blocks)
    goal = total / (opts['nparts'] or 1)
    chunks, cur, acc = [], [], 0
    for s, e in test_blocks:
        if cur and acc >= goal * 0.9:
            chunks.append(cur); cur, acc = [], 0
        cur.append((s, e)); acc += e - s + 1
    if cur:
        chunks.append(cur)

    names, ranges_text = [], []
    names.append(f"01_{base_name[0].lower() + base_name[1:]}_base.py" if not opts['overrides'].get(1) else f"01_{opts['overrides'][1]}.py")
    header_src = ''.join(lines[:cls.lineno - 1]) + class_line + base_body
    ranges_text.append(header_src)
    for i, chunk in enumerate(chunks, 2):
        sub = opts['overrides'].get(i) or f'{base_name.lower()}{i - 1:02d}'
        names.append(f'{i:02d}_{sub}.py')
        body = ''.join(''.join(lines[s - 1:e]) for s, e in chunk)
        ranges_text.append(f'class {base_name}Part{i - 1:02d}({base_name}):\n' + body)

    return names, ranges_text, cls


def main():
    path, parts_dir, header_end = sys.argv[1], sys.argv[2], int(sys.argv[3])
    opts = parse_args(sys.argv[4:])

    with open(path, encoding='utf-8', newline='') as f:
        lines = f.readlines()

    if opts['cls']:
        tree = ast.parse(''.join(lines))
        names, text_bodies, cls = split_class(path, opts, lines, tree)
        print(f'{path}: class {opts["cls"]} -> {len(names)} parts')
        for n, t in zip(names, text_bodies):
            print(f'  {n:55s} {t.count(chr(10)):>5} lines')
        if not opts['apply']:
            return
        os.makedirs(parts_dir, exist_ok=True)
        for n, t in zip(names, text_bodies):
            with open(os.path.join(parts_dir, n), 'w', encoding='utf-8', newline='') as f:
                f.write(t)
        modname = os.path.splitext(os.path.basename(path))[0]
        tail = ''.join(lines[cls.end_lineno:])
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(lines[:cls.lineno - 1]))
            f.write(loader_text(parts_dir, modname))
            f.write(tail)
        print('APPLIED')
        return

    blocks = top_blocks(lines)
    parts = split_flat(path, parts_dir, header_end, opts, lines, blocks)

    total = sum(e - s + 1 for s, e in parts)
    print(f'{path}: header 1-{header_end} ({header_end} lines), {len(parts)} parts, {total} body lines')
    names = []
    for idx, (s, e) in enumerate(parts, 1):
        names.append(part_name(idx, lines[s - 1:e], opts['overrides']))
        banner = first_banner(lines[s - 1:e]) or names[-1]
        print(f'  {names[-1]:55s} {s:>6}-{e:<6}  {e - s + 1:>5} lines   [{banner}]')
    if not opts['apply']:
        return

    write_parts(parts_dir, names, parts, lines)

    modname = os.path.splitext(os.path.basename(path))[0]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.writelines(lines[:header_end])
        f.write(loader_text(parts_dir, modname))

    out = lines[:header_end]
    for name in names:
        with open(os.path.join(parts_dir, name), encoding='utf-8', newline='') as vf:
            out += vf.readlines()
    assert out == lines, f'LINE MISMATCH in {path}: {len(out)} vs {len(lines)}'
    print(f'VERIFIED: header + {len(names)} parts == original ({len(lines)} lines)')


if __name__ == '__main__':
    main()
