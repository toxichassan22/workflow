# -*- coding: utf-8 -*-
"""Deep i18n gap scan — frontend.

Robust JS string tokenizer (comments only outside strings, escapes, template
literals split at ${...}). Each Arabic literal is deglued to the text the
DOM would actually show, then classified:

  uncovered      = no English in EN_AUTO / dicts -> stays Arabic in EN mode
  glue_gap       = literal glued to runtime values (+ concat or ${}): the
                   rendered node is longer than the key, so even a covered
                   core never exact-matches -> stays Arabic too
  ok             = standalone covered unit
"""
import json
import re
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = Path(__file__).resolve().parent
AR_RE = re.compile(r'[؀-ۿ]')

JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js',
    '05-market-competitors.js', '05a-market-summary-chat.js', '06-team.js',
    '07-project-form/01_form_sections.js',
    '07-project-form/02_section_versions.js',
    '08-location-maps/01_tables_approvals.js',
    '08-location-maps/02_catchment_edits.js',
    '09-financial/01_financial_format.js',
    '09-financial/02_formulas_calc.js',
    '10-financial-report-timeline/01_report_collect.js',
    '10-financial-report-timeline/02_timeline_sidebar.js',
    '10-financial-report-timeline/03_timeline_board.js',
    '11-land-croquis/01_croquis_survey.js',
    '11-land-croquis/02_map_edits.js',
    '11-land-croquis/03_interactive_map.js',
    '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '12-files-media/02a_visual_concept_sections.js',
    '12-files-media/03_visual_concept_sketch.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js',
    '13-visual/03_tenant_slide_generation.js', '14-slides-gen/01_undo.js',
    '14-slides-gen/02_element_editing.js', '14-slides-gen/03_slide_regeneration.js',
    '15-slide-edit-chat/01_render_inline_edit.js',
    '15-slide-edit-chat/02_designer_chat.js',
    '15-slide-edit-chat/03_agent_checklist.js',
    '15-slide-edit-chat/04_slide_activity.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js',
    '16-presentations-export/02a_admin_charts.js',
    '16-presentations-export/03_export_delivery.js',
    '16-presentations-export/04_sag_company_create.js',
    '17-admin-boot/01_training_rules.js',
    '17-admin-boot/02_users_roles.js',
    '17-admin-boot/03_training_chat_sessions.js', '18-landloom-ops.js',
    '18-landloom-ops/01_package_slider.js', '19-notifications.js',
)

GLUE_RE = re.compile(r"^[)\]}>\"'`\\\s]+")
GLUE_TAIL_RE = re.compile(r"[\(\[\{\"'`\\\s:;,]+$")
ATTR_GLUE_RE = re.compile(r'^(?:selected|hidden|checked|disabled)\s*>\s*')
CODEISH_RE = re.compile(
    r'(=>|===|!==|\|\||&&|\$\{|const |let |var |return |function |'
    r'\.(?=[a-zA-Z_$])|;[^؀-ۿ]|[a-zA-Z_$]\s*=)')


def load_dicts():
    src = '\n'.join(p.read_text(encoding='utf-8')
                    for p in sorted((ROOT / 'assets' / 'i18n').glob('*.js')))
    dicts = {}
    for lang in ('AR', 'EN'):
        m = re.search(r'/\*I18N_%s_BEGIN\*/(.*?)/\*I18N_%s_END\*/' % (lang, lang),
                      src, re.S)
        dicts[lang.lower()] = json.loads(m.group(1))
    auto = {}
    for b in re.findall(
            r'/\*I18N_EN_AUTO_BEGIN\*/(.*?)/\*I18N_EN_AUTO_END\*/', src, re.S):
        auto.update(json.loads(b))
    return dicts, auto


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def deglue(value):
    previous = None
    while previous != value:
        previous = value
        value = value.replace("\\'", "'").replace('\\"', '"')
        value = GLUE_RE.sub('', value)
        value = ATTR_GLUE_RE.sub('', value)
        value = GLUE_TAIL_RE.sub('', value)
        value = norm(value)
    return value


def js_literals(src):
    """(text, is_template_piece, pos, terminated_by_interpolation)."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j == -1 else j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = n if j == -1 else j + 2
            continue
        if c in '\'"':
            quote = c
            j, buf = i + 1, []
            while j < n:
                ch = src[j]
                if ch == '\\':
                    buf.append(src[j:j + 2]); j += 2; continue
                if ch == quote or ch == '\n':
                    break
                buf.append(ch); j += 1
            out.append((''.join(buf), False, i, False))
            i = j + 1
            continue
        if c == '`':
            j = i + 1
            buf = []
            while j < n:
                ch = src[j]
                if ch == '\\':
                    buf.append(src[j:j + 2]); j += 2; continue
                if ch == '`':
                    break
                if ch == '$' and j + 1 < n and src[j + 1] == '{':
                    out.append((''.join(buf), True, i, True))
                    buf = []
                    depth = 1
                    j += 2
                    while j < n and depth:
                        if src[j] == '{':
                            depth += 1
                        elif src[j] == '}':
                            depth -= 1
                        j += 1
                    # piece resumes here; its pos is i (template start)
                    continue
                buf.append(ch); j += 1
            out.append((''.join(buf), True, i, False))
            i = j + 1
            continue
        i += 1
    return out


def markup_units(markup):
    """(kind, text) units the DOM pass sees: text nodes + chrome attrs."""
    body = re.sub(r'<!--[\s\S]*?-->', '', markup)
    found = []
    for chunk in re.split(r'<[^>]+>', body):
        v = deglue(chunk)
        if v and AR_RE.search(v):
            found.append(('text', v))
    for tag in re.findall(r'<[^>]*>', body):
        for m in re.finditer(r'([a-zA-Z-]+)\s*=\s*"([^"]*)"', tag):
            if m.group(1).lower() in ('placeholder', 'title', 'aria-label',
                                      'alt', 'value'):
                v = norm(m.group(2))
                if v and AR_RE.search(v):
                    found.append(('attr', v))
    return found


def main():
    dicts, auto = load_dicts()
    cov_vals = set(dicts['ar'].values()) | set(dicts['en'].values())

    def covered(v):
        return v in auto or v in cov_vals

    rows = []
    for name in JS_ORDER:
        p = ROOT / 'assets' / 'js' / name
        src = p.read_text(encoding='utf-8')
        for lit, is_tpl, pos, ended_by_interp in js_literals(src):
            if not AR_RE.search(lit):
                continue
            line = src.count('\n', 0, pos) + 1
            tail = src[pos + len(lit) + 2:pos + len(lit) + 60]
            head = src[max(0, pos - 60):pos]
            concat = bool(tail.lstrip().startswith('+')
                          or head.rstrip().endswith('+'))
            glued = is_tpl or concat or ended_by_interp
            if '<' in lit:
                for kind, v in markup_units(lit):
                    # a text node at a glued edge still renders longer text
                    rows.append(dict(file=name, line=line, text=v,
                                     glued=False, markup=True))
            else:
                v = deglue(lit)
                if v:
                    rows.append(dict(file=name, line=line, text=v, glued=glued,
                                     markup=False))
    for kind, v in markup_units((ROOT / 'index.html').read_text(encoding='utf-8')):
        rows.append(dict(file='index.html', line=0, text=v, glued=False,
                         markup=True))

    seen = {}
    for r in rows:
        if r['text'] in seen:
            seen[r['text']]['glued'] = seen[r['text']]['glued'] and r['glued']
            continue
        seen[r['text']] = r

    uncovered, glue_gaps, skip = [], [], []
    ok = 0
    for text, r in sorted(seen.items()):
        if len(text) <= 2 or CODEISH_RE.search(text):
            skip.append(r)
            continue
        if re.fullmatch(r'[\[\]/\-()\s؀-ۿ,]+', text) and re.search(r'[\[\]/]', text):
            skip.append(r)
            continue
        if not covered(text):
            (glue_gaps if r['glued'] else uncovered).append(r)
        elif r['glued']:
            glue_gaps.append(r)
        else:
            ok += 1

    print('=== UNCOVERED standalone (rendered node ~== literal, no English): '
          '%d ===' % len(uncovered))
    for r in uncovered:
        print('%s:%d  %s' % (r['file'], r['line'], r['text'][:110]))
    print()
    print('=== GLUED pieces (part of a longer runtime string; exact match '
          'impossible): %d ===' % len(glue_gaps))
    for r in glue_gaps:
        flag = '' if covered(r['text']) else '  [core also uncovered]'
        print('%s:%d  %s%s' % (r['file'], r['line'], r['text'][:110], flag))
    print()
    print('ok covered: %d   skipped(code/punct): %d' % (ok, len(skip)))


if __name__ == '__main__':
    main()
