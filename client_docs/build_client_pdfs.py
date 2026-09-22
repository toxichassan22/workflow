# -*- coding: utf-8 -*-
"""Build client-ready HTML sources for the two documentation PDFs:
   - file-tree.html     (file-tree.md + a line count for every file)
   - site-overview.html (SITE_OVERVIEW.md rendered as a styled RTL document)
   Printing to PDF is done by print_pdfs.js (Playwright/Chrome)."""

import html
import os
import re
from datetime import datetime

ROOT = r"D:\workflow"
OUT = os.path.join(ROOT, "client_docs")
TREE_MD = os.path.join(ROOT, "file-tree.md")
OVERVIEW_MD = os.path.join(ROOT, "SITE_OVERVIEW.md")

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿"
    "︀-️‍]+"
)


def count_lines(path):
    """(line_count, kind) — kind is text / binary / missing."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
            if b"\x00" in head:
                return None, "binary"
            data = head + fh.read()
    except OSError:
        return None, "missing"
    text = data.decode("utf-8", errors="replace")
    return len(text.splitlines()), "text"


def parse_tree():
    """Parse file-tree.md into display rows + document statistics."""
    with open(TREE_MD, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    generated_raw = ""
    if lines and lines[0].startswith("**Generated:**"):
        generated_raw = lines[0].replace("**Generated:**", "").strip()
        lines = lines[1:]
    if lines and set(lines[0].strip()) == {"="}:
        lines = lines[1:]

    rows = []
    stack = []
    for ln in lines:
        if not ln.strip():
            continue
        m = re.match(r"^(.*?)((?:├──|└──) )(.*)$", ln)
        if not m:
            continue
        prefix, marker, rest = m.group(1), m.group(2), m.group(3)
        depth = len(prefix) // 4
        is_dir = rest.startswith("\U0001F4C1")
        name = EMOJI_RE.sub("", rest).strip()
        display = prefix + marker + name
        row = {"display": display, "is_dir": is_dir}
        if is_dir:
            stack = stack[:depth] + [name]
            row["comps"] = tuple(stack)
            row["lines"] = None
            row["kind"] = "dir"
        else:
            comps = tuple(stack[:depth]) + (name,)
            full = os.path.join(ROOT, *comps)
            cnt, kind = count_lines(full)
            row["comps"] = comps
            row["lines"] = cnt
            row["kind"] = kind
        rows.append(row)

    # line subtotals for every directory (files below it, text files only)
    totals = {}
    for r in rows:
        if r["is_dir"]:
            continue
        for k in range(1, len(r["comps"]) + 1):
            key = r["comps"][:k]
            totals[key] = totals.get(key, 0) + (r["lines"] or 0)
    for r in rows:
        if r["is_dir"]:
            r["lines"] = totals.get(r["comps"], 0)

    files = [r for r in rows if not r["is_dir"]]
    dirs = [r for r in rows if r["is_dir"]]
    stats = {
        "files": len(files),
        "dirs": len(dirs),
        "lines": sum(r["lines"] or 0 for r in files),
        "missing": sum(1 for r in files if r["kind"] == "missing"),
        "binary": sum(1 for r in files if r["kind"] == "binary"),
    }

    generated = generated_raw
    try:
        dt = datetime.strptime(generated_raw, "%m/%d/%Y, %I:%M:%S %p")
        hour = dt.hour % 12 or 12
        mer = "م" if dt.hour >= 12 else "ص"
        generated = f"{dt.day}/{dt.month}/{dt.year} — {hour}:{dt.minute:02d} {mer}"
    except Exception:
        pass
    return rows, stats, generated

BASE_CSS = """
@font-face{font-family:'LLArabic';src:url('../assets/fonts/TheSansArabic-Light.otf') format('opentype');font-weight:300 500;font-style:normal;font-display:swap}
@font-face{font-family:'LLArabic';src:url('../assets/fonts/BahijTheSansArabic-Bold.ttf') format('truetype');font-weight:600 800;font-style:normal;font-display:swap}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{font-family:'LLArabic','Segoe UI',Tahoma,sans-serif;color:#1e2733;font-size:10pt;line-height:1.65;background:#fff}
.doc-head{border-top:5px solid #B8963E;padding-top:14px;margin-bottom:16px}
.brand{font-family:Consolas,'Segoe UI',monospace;letter-spacing:.35em;font-size:11pt;color:#123B2F;font-weight:700}
.doc-kind{font-size:8.5pt;color:#B8963E;letter-spacing:.18em;margin-top:2px}
h1{font-size:19pt;color:#123B2F;margin:10px 0 4px;font-weight:700;line-height:1.35}
.sub{color:#5b6675;font-size:10pt;margin:0 0 8px}
.meta{font-size:8.5pt;color:#7a8494}
.stats{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.stat{border:1px solid #dfe4ec;border-right:3px solid #123B2F;padding:6px 12px;min-width:128px}
.stat b{display:block;font-size:14pt;color:#123B2F;font-weight:700;line-height:1.3}
.stat span{font-size:8pt;color:#5b6675}
.legend{font-size:8.5pt;color:#5b6675;margin:12px 0 14px;padding:9px 12px;background:#f6f8fa;border:1px solid #e6eaef;line-height:1.9}
h2{font-size:13pt;color:#123B2F;border-bottom:2px solid #B8963E;padding-bottom:4px;margin:24px 0 10px;break-after:avoid;font-weight:700}
h3{font-size:11pt;color:#123B2F;margin:16px 0 6px;break-after:avoid;font-weight:700}
p{margin:6px 0}
ul{margin:6px 0 10px;padding-inline-start:22px}
li{margin:3px 0}
a{color:#0f5a45;text-decoration:none}
code{font-family:Consolas,'Courier New',monospace;font-size:8.5pt;background:#f2f4f7;padding:0 4px;border-radius:3px;direction:ltr;unicode-bidi:isolate;color:#0f3d2e}
table{width:100%;border-collapse:collapse;margin:8px 0 14px;font-size:9pt}
th{background:#123B2F;color:#fff;font-weight:700;text-align:right}
th,td{border:1px solid #d9dee6;padding:5px 7px;vertical-align:top}
tbody tr:nth-child(even){background:#f7f9fb}
tr{break-inside:avoid}
strong{color:#123B2F;font-weight:700}
hr{border:0;border-top:1px solid #e6eaef;margin:16px 0}
.tree{direction:ltr}
.tree-head{display:flex;justify-content:space-between;gap:16px;font-size:8.5pt;color:#fff;background:#123B2F;padding:5px 12px;font-weight:700;margin-bottom:3px}
.trow{display:flex;justify-content:space-between;gap:16px;font-family:Consolas,'Cascadia Mono',monospace;font-size:8.6pt;padding:1.5px 12px;break-inside:avoid;line-height:1.5}
.trow:nth-child(even){background:#f7f9fb}
.tpath{white-space:pre;overflow-wrap:anywhere}
.tnum{color:#3c4757;font-variant-numeric:tabular-nums;min-width:74px;text-align:right;flex:none}
.trow.dir .tpath{color:#123B2F;font-weight:700}
.trow.dir .tnum{color:#9aa4b2}
.tnum.na{color:#9aa4b2}
.footnote{font-size:8pt;color:#7a8494;margin-top:18px;padding-top:8px;border-top:1px solid #e6eaef}
"""




def _md_inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    # stash code spans first so their literal * / _ cannot break bold/italic,
    # then restore them (handles **bold `code*` bold**)
    codes = []
    text = re.sub(
        r"`([^`]+)`",
        lambda m: codes.append(m.group(1)) or "\x00%d\x00" % (len(codes) - 1),
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(
        "\x00(\\d+)\x00",
        lambda m: "<code>%s</code>" % codes[int(m.group(1))],
        text,
    )
    return text



def _md_cells(line):
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _md_is_sep(line):
    cells = _md_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _md_table(block):
    has_sep = len(block) > 1 and _md_is_sep(block[1])
    rows = [_md_cells(l) for l in block if not _md_is_sep(l)]
    head = rows[0] if has_sep and rows else None
    body = rows[1:] if has_sep and rows else rows
    out = ["<table>"]
    if head is not None:
        out.append("<thead><tr>")
        out.extend(f"<th>{_md_inline(c)}</th>" for c in head)
        out.append("</tr></thead>")
    out.append("<tbody>")
    for r in body:
        out.append("<tr>")
        out.extend(f"<td>{_md_inline(c)}</td>" for c in r)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


_SPECIAL_RE = re.compile(r"^(#{1,4}\s| {0,3}-\s|\s*\|)")


def md_to_html(md_text, skip_h1=False):
    # 1) merge soft-wrapped lines (paragraph and bullet continuations)
    merged = []
    for raw in md_text.splitlines():
        s = raw.rstrip()
        if not s.strip():
            merged.append("")
        elif _SPECIAL_RE.match(s) or s.strip() == "---" or not merged or not merged[-1]:
            merged.append(s)
        else:
            merged[-1] = merged[-1].rstrip() + " " + s.strip()

    # 2) walk the merged lines as blocks
    out = []
    ul_depth = 0
    title = ""

    def close_lists(depth=0):
        nonlocal ul_depth
        while ul_depth > depth:
            out.append("</ul>")
            ul_depth -= 1

    i, n = 0, len(merged)
    while i < n:
        line = merged[i]
        if not line.strip() or line.strip() == "---":
            close_lists(0)
            i += 1
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            close_lists(0)
            lvl, text = len(h.group(1)), h.group(2).strip()
            if lvl == 1 and skip_h1 and not title:
                title = text
            else:
                out.append(f"<h{lvl}>{_md_inline(text)}</h{lvl}>")
            i += 1
            continue
        if line.lstrip().startswith("|"):
            close_lists(0)
            block = []
            while i < n and merged[i].lstrip().startswith("|"):
                block.append(merged[i])
                i += 1
            out.append(_md_table(block))
            continue
        b = re.match(r"^(\s*)-\s+(.*)$", line)
        if b:
            depth = min(len(b.group(1)) // 2 + 1, 4)
            while ul_depth > depth:
                out.append("</ul>")
                ul_depth -= 1
            while ul_depth < depth:
                out.append("<ul>")
                ul_depth += 1
            out.append(f"<li>{_md_inline(b.group(2))}</li>")
            i += 1
            continue
        close_lists(0)
        out.append(f"<p>{_md_inline(line.strip())}</p>")
        i += 1
    close_lists(0)
    return "".join(out), title


def _page(title, direction, body_html):
    dir_attr = f' dir="{direction}"' if direction else ""
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="ar"{dir_attr}>\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{BASE_CSS}</style>\n</head>\n<body>\n"
        f"{body_html}\n</body>\n</html>\n"
    )


def build_tree_html(rows, stats, generated):
    parts = []
    for r in rows:
        disp = html.escape(r["display"])
        if r["is_dir"]:
            cls, num, num_cls, tip = "trow dir", f'{r["lines"]:,}', "tnum", ' title="مجموع أسطر ملفات المجلد"'
        elif r["kind"] == "missing":
            cls, num, num_cls, tip = "trow", "—", "tnum na", ' title="الملف غير موجود"'
        elif r["kind"] == "binary":
            cls, num, num_cls, tip = "trow", "—", "tnum na", ' title="ملف غير نصي"'
        else:
            cls, num, num_cls, tip = "trow", f'{r["lines"]:,}', "tnum", ""
        parts.append(
            f'<div class="{cls}"><span class="tpath" dir="ltr">{disp}</span>'
            f'<span class="{num_cls}"{tip}>{num}</span></div>'
        )
    legend = (
        "دليل: عدد الأسطر يخص الملفات النصية فقط، والرقم الرمادي بجانب المجلد هو مجموع "
        "أسطر ملفاته. الرمز (—): ملف ثنائي (صور/خطوط/بيانات) أو غير موجود في القرص."
    )
    body = f"""
<div class="doc-head" dir="rtl">
  <div class="brand">LANDLOOM</div>
  <div class="doc-kind">توثيق تقني</div>
  <h1>شجرة ملفات المشروع</h1>
  <p class="sub">مستودع منصة LandLoom لتوليد العروض التقديمية وملفات الاستثمار العقارية بالذكاء الاصطناعي</p>
  <div class="meta">تاريخ توليد الشجرة: {html.escape(generated)}</div>
  <div class="stats">
    <div class="stat"><b>{stats['files']:,}</b><span>ملف</span></div>
    <div class="stat"><b>{stats['dirs']:,}</b><span>مجلد</span></div>
    <div class="stat"><b>{stats['lines']:,}</b><span>سطر نصي إجمالاً</span></div>
    <div class="stat"><b>{stats['binary']:,}</b><span>ملف غير نصي</span></div>
    <div class="stat"><b>{stats['missing']:,}</b><span>غير موجود بالقرص</span></div>
  </div>
</div>
<div class="legend" dir="rtl">{legend}</div>
<div class="tree">
  <div class="tree-head"><span dir="rtl">المسار</span><span dir="rtl">عدد الأسطر</span></div>
  {chr(10).join(parts)}
</div>
<div class="footnote" dir="rtl">LandLoom — وثيقة تقنية مُعدّة للعميل. المصدر: file-tree.md</div>
"""
    return _page("شجرة ملفات المشروع — LandLoom", "ltr", body)


def build_overview_html(body_md, today):
    body, title = md_to_html(body_md, skip_h1=True)
    head = f"""
<div class="doc-head">
  <div class="brand">LANDLOOM</div>
  <div class="doc-kind">توثيق تقني شامل</div>
  <h1>{html.escape(title or 'التوثيق الشامل للمنصة')}</h1>
  <p class="sub">مرجع واحد لبنية النظام وتقنياته وأدواره — مُعدّ للعميل</p>
  <div class="meta">landloom.ai — نسخة الوثيقة: {today}</div>
</div>
"""
    foot = '<div class="footnote">LandLoom — التوثيق الشامل للمنصة. المصدر: SITE_OVERVIEW.md</div>'
    return _page(title or "التوثيق الشامل للمنصة — LandLoom", "rtl", head + body + foot)


def main():
    rows, stats, generated = parse_tree()
    tree_path = os.path.join(OUT, "file-tree.html")
    with open(tree_path, "w", encoding="utf-8") as fh:
        fh.write(build_tree_html(rows, stats, generated))

    with open(OVERVIEW_MD, encoding="utf-8") as fh:
        md_text = fh.read()
    overview_path = os.path.join(OUT, "site-overview.html")
    with open(overview_path, "w", encoding="utf-8") as fh:
        fh.write(build_overview_html(md_text, datetime.now().strftime("%d/%m/%Y")))

    print(f"tree: {stats['files']} files, {stats['dirs']} dirs, {stats['lines']} lines, "
          f"missing={stats['missing']}, binary={stats['binary']}")
    print("wrote", tree_path)
    print("wrote", overview_path)


if __name__ == "__main__":
    main()


