# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project timeline — phase data normalization + the canonical Gantt slide.
#
# parse_timeline_phases reads the draft's timeline table (current date-pair rows
# and the older year/quarter/duration rows) onto one normalized shape with
# absolute month indexes; _build_timeline_slide renders those phases as a
# colored Gantt on a shared date axis — the same reading as the project-data
# timeline board — so the slide can never ship without its chart.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TIMELINE_QUARTERS = ('Q1', 'Q2', 'Q3', 'Q4')


def _timeline_project_start_index(project_data):
    """Project start as an absolute month index (year*12 + month-1), or None.

    The client picks a full start date («2030-02-15»); drafts saved before that stored
    month+year, and older ones a bare start year that maps to January.
    """
    source = project_data if isinstance(project_data, dict) else {}
    raw = str(source.get('timeline_start_date') or '').strip()
    match = re.match(r'^(\d{4})-(\d{1,2})(?:-\d{1,2})?$', raw)
    if match and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)) * 12 + (int(match.group(2)) - 1)
    legacy = str(source.get('timeline_start_year') or '').strip()
    if re.match(r'^\d{4}$', legacy):
        return int(legacy) * 12
    return None


def _format_timeline_month(index):
    return f'{(index % 12) + 1}/{index // 12}'


def compute_timeline_end(year, quarter, duration):
    """Inclusive end as a project-relative year/quarter plus its month offset from start."""
    try:
        start_year = int(year)
        quarter_index = TIMELINE_QUARTERS.index(str(quarter or '').strip())
        months = int(duration)
    except (TypeError, ValueError):
        return None
    if start_year <= 0 or months <= 0:
        return None
    end_month = (start_year - 1) * 12 + quarter_index * 3 + months - 1
    return {
        'year': str(end_month // 12 + 1),
        'quarter': TIMELINE_QUARTERS[(end_month % 12) // 3],
        'month_index': end_month,
    }


def _parse_timeline_date(raw):
    """A stored phase date — «YYYY-MM-DD», with «YYYY-MM» landing on its first day."""
    match = re.match(r'^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$', str(raw or '').strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    day = int(match.group(3) or 1)
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    return (year, month, day)


def _timeline_date_label(raw, date_tuple):
    """Day-precise label; a month-only stored value keeps the bare month/year look."""
    year, month, day = date_tuple
    if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(raw or '').strip()):
        return f'{day}/{month}/{year}'
    return f'{month}/{year}'


def _timeline_phase_from_dates(item, start_index):
    """Normalize a date-pair phase {name, start, end, notes} onto the shared phase shape."""
    import datetime as _dt
    phase = {
        'name': str(item.get('name') or '').strip(),
        'year': '',
        'quarter': '',
        'duration': '',
        'endYear': '',
        'endQuarter': '',
        'notes': str(item.get('notes') or '').strip(),
    }
    start_d = _parse_timeline_date(item.get('start'))
    end_d = _parse_timeline_date(item.get('end'))
    if not start_d or not end_d or end_d < start_d:
        return phase
    phase['start_label'] = _timeline_date_label(item.get('start'), start_d)
    phase['end_label'] = _timeline_date_label(item.get('end'), end_d)
    start_date = _dt.date(*start_d)
    end_date = _dt.date(*end_d)
    phase['duration'] = str(max(1, round(((end_date - start_date).days + 1) / 30.4375)))
    # Absolute month indexes place the phase on a shared axis — the slide Gantt
    # positions its bar straight from them without reparsing the labels.
    phase['start_month_index'] = start_d[0] * 12 + start_d[1] - 1
    phase['end_month_index'] = end_d[0] * 12 + end_d[1] - 1
    if start_index is not None:
        # Relative project years/quarters stay available for any consumer that still frames
        # phases on the project's own axis.
        rel_start = (start_d[0] * 12 + start_d[1] - 1) - start_index
        rel_end = (end_d[0] * 12 + end_d[1] - 1) - start_index
        phase['year'] = str(max(1, rel_start // 12 + 1))
        phase['quarter'] = TIMELINE_QUARTERS[(rel_start % 12) // 3]
        phase['endYear'] = str(max(1, rel_end // 12 + 1))
        phase['endQuarter'] = TIMELINE_QUARTERS[(rel_end % 12) // 3]
    return phase


def parse_timeline_phases(project_data):
    """Return named timeline phases from the draft table, including notes.

    Current drafts store each phase as a start/end date pair; rows saved by the earlier
    quarter/duration table keep their project-relative years and are read on the same shape.
    """
    source = project_data if isinstance(project_data, dict) else {}
    raw = source.get('timeline_table_data')
    if raw in (None, '', []):
        raw = source.get('timelineRows')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    start_index = _timeline_project_start_index(source)
    # A bare start year with no start date marks a pre-migration draft: its rows hold calendar
    # years and January-anchored quarters, so shift them onto the relative axis.
    legacy_start_year = None
    if not str(source.get('timeline_start_date') or '').strip():
        legacy = str(source.get('timeline_start_year') or '').strip()
        if re.match(r'^\d{4}$', legacy):
            legacy_start_year = int(legacy)
    phases = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        if 'start' in item or 'end' in item:
            phases.append(_timeline_phase_from_dates(item, start_index))
            continue
        year = str(item.get('year') or '').strip()
        quarter = str(item.get('quarter') or '').strip()
        duration = str(item.get('duration') or '').strip()
        end_year = str(item.get('endYear') or '').strip()
        end_quarter = str(item.get('endQuarter') or '').strip()
        if legacy_start_year is not None:
            if year.isdigit() and int(year) >= 1000:
                year = str(max(1, int(year) - legacy_start_year + 1))
            if end_year.isdigit() and int(end_year) >= 1000:
                end_year = str(max(1, int(end_year) - legacy_start_year + 1))
        computed = compute_timeline_end(year, quarter, duration)
        if not end_year or not end_quarter:
            if computed:
                end_year = end_year or computed['year']
                end_quarter = end_quarter or computed['quarter']
        phase = {
            'name': name,
            'year': year,
            'quarter': quarter,
            'duration': duration,
            'endYear': end_year,
            'endQuarter': end_quarter,
            'notes': str(item.get('notes') or '').strip(),
        }
        # Relative month indexes anchor the phase on the shared Gantt axis; the
        # project start lifts them onto absolute calendar months when set, while
        # a calendar-year row is already absolute on its own.
        try:
            rel_start_m = (int(year) - 1) * 12 + TIMELINE_QUARTERS.index(str(quarter).strip()) * 3
        except (TypeError, ValueError):
            rel_start_m = None
        rel_end_m = computed['month_index'] if computed else None
        if rel_end_m is None:
            try:
                rel_end_m = (int(end_year) - 1) * 12 + TIMELINE_QUARTERS.index(str(end_quarter).strip()) * 3 + 2
            except (TypeError, ValueError):
                rel_end_m = None
        if rel_start_m is not None:
            phase['start_month_index'] = start_index + rel_start_m if start_index is not None else rel_start_m
        if rel_end_m is not None:
            phase['end_month_index'] = start_index + rel_end_m if start_index is not None else rel_end_m
        if start_index is not None:
            try:
                phase['start_label'] = _format_timeline_month(
                    start_index + (int(year) - 1) * 12 + TIMELINE_QUARTERS.index(quarter) * 3)
            except (TypeError, ValueError):
                pass
            end_month_index = computed['month_index'] if computed else None
            if end_month_index is None:
                try:
                    end_month_index = (
                        (int(end_year) - 1) * 12 + TIMELINE_QUARTERS.index(end_quarter) * 3 + 2)
                except (TypeError, ValueError):
                    end_month_index = None
            if end_month_index is not None:
                phase['end_label'] = _format_timeline_month(start_index + end_month_index)
        phases.append(phase)

    if not phases:
        years_val = source.get('timeline_years') or source.get('development_years') or source.get('development_duration_years')
        has_start = start_index is not None or bool(str(source.get('timeline_start_date') or '').strip()) or bool(str(source.get('timeline_start_year') or '').strip())
        years_num = 0
        if years_val:
            try:
                years_num = int(str(years_val).strip())
            except (ValueError, TypeError):
                years_num = 0
        if years_num <= 0 and has_start:
            years_num = 3
        if years_num > 0:
            total_months = max(12, years_num * 12)
            default_phase_specs = [
                ('التصميم والدراسات والتراخيص', 0.15, 'إعداد وتدقيق المخططات الهندسية واستخراج رخص البناء والاعتمادات النظامية'),
                ('تجهيز الموقع والأساسات والهيكل الإنشائي', 0.25, 'أعمال تسوية الموقع والحفر وتنفيذ الأساسات والهيكل الخرساني والإنشائي'),
                ('استكمال الهيكل وأعمال الكهرباء والميكانيكا', 0.25, 'تمديد الشبكات الكهروميكانيكية وأنظمة التكييف والسلامة والإنذار'),
                ('التشطيبات والأعمال الخارجية وتنسيق الموقع', 0.20, 'تنفيذ التشطيبات المعمارية والواجهات وتنسيق الموقع العام والمسطحات'),
                ('الاختبارات والتسليم والتسويق والتشغيل', 0.15, 'الفحص والتشغيل التجريبي واستخراج رخص الإشغال والإطلاق والتسليم'),
            ]
            current_month = 0
            for idx, (p_name, weight, p_notes) in enumerate(default_phase_specs):
                if idx == len(default_phase_specs) - 1:
                    dur = max(2, total_months - current_month)
                else:
                    dur = max(2, round(total_months * weight))
                start_m = current_month
                end_m = start_m + dur - 1
                y_start = str(start_m // 12 + 1)
                q_start = TIMELINE_QUARTERS[(start_m % 12) // 3]
                y_end = str(end_m // 12 + 1)
                q_end = TIMELINE_QUARTERS[(end_m % 12) // 3]
                p = {
                    'name': p_name,
                    'year': y_start,
                    'quarter': q_start,
                    'duration': str(dur),
                    'endYear': y_end,
                    'endQuarter': q_end,
                    'notes': p_notes,
                    'start_month_index': (start_index + start_m) if start_index is not None else start_m,
                    'end_month_index': (start_index + end_m) if start_index is not None else end_m,
                }
                if start_index is not None:
                    p['start_label'] = _format_timeline_month(start_index + start_m)
                    p['end_label'] = _format_timeline_month(start_index + end_m)
                phases.append(p)
                current_month += dur

    return phases


def format_timeline_phase_line(phase):
    def _point(year, quarter, label):
        if label:
            return label
        parts = []
        if year:
            parts.append(f'سنة {year}')
        if quarter:
            parts.append(f'الربع {str(quarter).lstrip("Q")}')
        return ' '.join(parts)

    start = _point(phase.get('year'), phase.get('quarter'), phase.get('start_label'))
    end = _point(phase.get('endYear'), phase.get('endQuarter'), phase.get('end_label'))
    span = f'{start} إلى {end}' if start and end else (start or end)
    duration = phase.get('duration')
    duration_text = f' لمدة {duration} شهر' if duration else ''
    notes = phase.get('notes')
    notes_text = f' — {notes}' if notes else ''
    detail = f'{span}{duration_text}' if span or duration_text else ''
    return f"{phase['name']}: {detail}{notes_text}".strip(': ').strip()


def _timeline_data_note(project_data):
    """Keep the phase table, including notes, outside the truncated project JSON."""
    phases = parse_timeline_phases(project_data)
    if not phases:
        return ''
    return (
        "\n\n## الجدول الزمني للمشروع — إلزامي في شريحة الجدول الزمني\n"
        "هذه المراحل مصدر الحقيقة. اعرض كل مرحلة مع بدايتها ومدتها ونهايتها المحسوبة.\n"
        "إذا وُجدت ملاحظة لمرحلة فاعرضها تحتها أو بجانبها دون حذف أو اختصار. إذا كانت الملاحظة فارغة فلا تعرض عنوانًا أو حقلًا أو مساحة للملاحظات في تلك المرحلة.\n"
        + '\n'.join(f'- {format_timeline_phase_line(phase)}' for phase in phases)
    )


def _mix_hex_colors(hex_a, hex_b, ratio=0.5):
    """Blend two brand colors so the Gantt rotates a coordinated colored palette."""
    ca = normalize_hex_color(hex_a, '#0b1f33')
    cb = normalize_hex_color(hex_b, '#c59a58')
    mixed = tuple(
        round(int(ca[i:i + 2], 16) * (1 - ratio) + int(cb[i:i + 2], 16) * ratio)
        for i in (1, 3, 5))
    return '#{:02x}{:02x}{:02x}'.format(*mixed)


def _timeline_gantt_axis(source, phases):
    """Absolute month-index bounds for the shared date axis, or None.

    The axis is the project period when the client set one — phases bleeding past
    it are clipped or pinned at an edge instead of stretching the board.
    """
    def month_index(value):
        parsed = _parse_timeline_date(value)
        return parsed[0] * 12 + parsed[1] - 1 if parsed else None

    dated = [p for p in phases
             if isinstance(p.get('start_month_index'), int)
             and isinstance(p.get('end_month_index'), int)
             and p['end_month_index'] >= p['start_month_index']]
    if not dated:
        return None
    axis_start = month_index(source.get('timeline_start_date'))
    axis_end = month_index(source.get('timeline_end_date'))
    if axis_start is None:
        axis_start = min(p['start_month_index'] for p in dated)
    if axis_end is None:
        axis_end = max(p['end_month_index'] for p in dated)
    if axis_end < axis_start:
        axis_start, axis_end = axis_end, axis_start
    return axis_start, axis_end, dated


def _timeline_gantt_html(axis_start, axis_end, dated, undated, palette, primary, accent):
    """The Gantt body: a month axis with gridlines, then one lane per phase whose
    bar is positioned and sized by its start/end months — the same reading as the
    project-data timeline board, colored from the brand palette."""
    span = max(1, axis_end - axis_start + 1)
    label_w = 215
    lane_h = max(34, min(56, int(360 / max(1, len(dated)))))
    side = 'right'  # the slide is dir=rtl — time flows right-to-left like the board
    # At ~48px per m/yyyy label on a ~950px chart, at most ~19 ticks stay readable —
    # long projects tick every few months instead of overlapping the axis labels.
    tick_step = next((step for step in (1, 2, 3, 4, 6, 12) if span / step <= 19), 24)
    ticks = list(range(axis_start, axis_end + 1, tick_step))

    tick_labels = []
    gridlines = []
    for tick in ticks:
        pct = (tick - axis_start) / span * 100
        is_year = (tick % 12) == 0
        # A label's inline-start edge anchors on its tick so the text sits just past
        # it inside the chart; the last tick hugs the axis end so its label never
        # slides off the chart's far edge.
        anchor = f'{side}:{pct:.2f}%' if pct <= 95 else f'{side}:calc(100% - 46px)'
        tick_labels.append(
            f'<span style="position:absolute;{anchor};top:7px;font-size:9.5px;white-space:nowrap;'
            f'padding-inline-start:4px;font-weight:{700 if is_year else 500};'
            f'color:{"#475569" if is_year else "#8a94a6"};">{_format_timeline_month(tick)}</span>')
        gridlines.append(
            f'<div style="position:absolute;{side}:{pct:.2f}%;top:0;bottom:0;width:0;'
            f'border-{side}:1px solid {"#d7dee6" if is_year else "#eef2f6"};"></div>')

    lanes = []
    for idx, phase in enumerate(dated, 1):
        bar_color = palette[(idx - 1) % len(palette)]
        bar_text = readable_text_color('#ffffff', bar_color)
        p_start, p_end = phase['start_month_index'], phase['end_month_index']
        is_out = p_start < axis_start or p_end > axis_end
        s_clamp, e_clamp = max(p_start, axis_start), min(p_end, axis_end)
        if e_clamp < axis_start:
            s_clamp = e_clamp = axis_start
        elif s_clamp > axis_end:
            s_clamp = e_clamp = axis_end
        start_pct = (s_clamp - axis_start) / span * 100
        width_pct = max(2.5, (e_clamp - s_clamp + 1) / span * 100)
        width_pct = min(width_pct, 100 - start_pct)
        dur = str(phase.get('duration') or '').strip()
        dur_text = f'{html_lib.escape(dur)} شهر' if dur else f'{e_clamp - s_clamp + 1} شهر'
        in_bar = (f'<span style="font-size:10px;font-weight:700;color:{bar_text};white-space:nowrap;'
                  f'overflow:hidden;text-overflow:ellipsis;padding:0 8px;">{dur_text}</span>'
                  if width_pct >= 9 else '')
        border = f'border:1.5px dashed #b45309;' if is_out else ''
        bar = (
            f'<div data-timeline-bar="1" style="position:absolute;top:5px;bottom:5px;'
            f'{side}:{start_pct:.2f}%;width:{width_pct:.2f}%;background:{bar_color};'
            f'border-radius:8px;{border}display:flex;align-items:center;justify-content:center;'
            f'overflow:hidden;">{in_bar}</div>')

        name = html_lib.escape(str(phase.get('name') or '—').strip() or '—')
        start_label = html_lib.escape(str(phase.get('start_label') or '').strip())
        end_label = html_lib.escape(str(phase.get('end_label') or '').strip())
        span_text = ' — '.join(part for part in (start_label, end_label) if part)
        notes = html_lib.escape(str(phase.get('notes') or '').strip())
        notes_html = (
            f'<div style="font-size:9.5px;color:#8a94a6;line-height:1.35;margin-top:1px;'
            f'overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">{notes}</div>'
            if notes and lane_h >= 46 else '')
        label_cell = (
            f'<div style="height:{lane_h}px;padding:5px 10px;border-bottom:1px solid #f1f5f9;'
            f'box-sizing:border-box;overflow:hidden;">'
            f'<div style="font-size:11.5px;font-weight:800;color:{primary};line-height:1.3;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'<span style="color:{bar_color};">{idx:02d}</span> {name}</div>'
            + (f'<div style="font-size:9.5px;color:#64748b;margin-top:1px;white-space:nowrap;'
               f'overflow:hidden;text-overflow:ellipsis;">{span_text}</div>' if span_text else '')
            + notes_html
            + '</div>')
        lane_row = (
            f'<div style="height:{lane_h}px;position:relative;border-bottom:1px solid #f1f5f9;'
            f'box-sizing:border-box;">{bar}</div>')
        lanes.append((label_cell, lane_row))

    label_cells_html = ''.join(item[0] for item in lanes)
    lane_rows_html = ''.join(item[1] for item in lanes)

    undated_html = ''
    if undated:
        chips = ''.join(
            f'<span style="border:1px dashed {accent};color:{primary};border-radius:12px;'
            f'padding:2px 10px;font-size:10px;font-weight:600;">'
            f'{html_lib.escape(str(p.get("name") or "").strip() or "—")}</span>'
            for p in undated)
        undated_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;'
            'padding:8px 4px 0;">'
            '<span style="font-size:10.5px;color:#64748b;font-weight:700;">مراحل غير مجدولة:</span>'
            f'{chips}</div>')

    return (
        '<div data-timeline-gantt="1" style="background:#ffffff;border:1px solid #e2e8f0;'
        'border-radius:12px;overflow:hidden;">'
        f'<div style="display:flex;border-bottom:1px solid #e2e8f0;background:#f8fafc;">'
        f'<div style="width:{label_w}px;flex:none;padding:9px 10px;font-size:10.5px;'
        f'font-weight:700;color:#64748b;">المرحلة التنفيذية</div>'
        f'<div style="flex:1;position:relative;height:30px;overflow:hidden;">{"".join(tick_labels)}</div>'
        '</div>'
        '<div style="display:flex;align-items:stretch;">'
        f'<div style="width:{label_w}px;flex:none;border-inline-end:1px solid #eef2f6;">{label_cells_html}</div>'
        f'<div style="flex:1;position:relative;min-width:0;">{"".join(gridlines)}{lane_rows_html}</div>'
        '</div>'
        f'{undated_html}'
        '</div>')


def _build_timeline_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the project timeline as a colored Gantt on a shared date axis.

    The layout mirrors the project-data timeline board — one lane per phase on a
    month axis — and it is deterministic, so the section always carries its chart
    instead of whichever composition the model happened to draw. Phases with no
    dates keep the former card pipeline, since there is no axis to draw them on.
    """
    source = source if isinstance(source, dict) else {}
    phases = parse_timeline_phases(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    secondary = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    title = html_lib.escape(str((slide or {}).get('title') or 'الجدول الزمني ومراحل التطوير'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    axis = _timeline_gantt_axis(source, phases)
    dated = axis[2] if axis else []
    dated_ids = {id(p) for p in dated}
    undated = [p for p in phases if id(p) not in dated_ids]
    sorted_dated = sorted(dated, key=lambda p: (p['start_month_index'], p['end_month_index']))

    if axis:
        axis_start, axis_end = axis[0], axis[1]
        total_months = axis_end - axis_start + 1
        span_years = total_months / 12
        years_text = str(int(span_years)) if span_years >= 1 and float(span_years).is_integer() else (
            str(round(span_years, 1)) if span_years >= 1 else '')
        duration_str = f"{total_months} شهر" + (f" ({years_text} سنوات)" if years_text else '')
        start_parsed = _parse_timeline_date(source.get('timeline_start_date'))
        end_parsed = _parse_timeline_date(source.get('timeline_end_date'))
        start_str = _timeline_date_label(source.get('timeline_start_date'), start_parsed) if start_parsed else (
            sorted_dated[0].get('start_label') or '—')
        end_str = _timeline_date_label(source.get('timeline_end_date'), end_parsed) if end_parsed else (
            sorted_dated[-1].get('end_label') or '—')
    else:
        total_months = sum(int(p.get('duration') or 0) for p in phases if str(p.get('duration') or '').isdigit())
        try:
            years_num = float(str(source.get('timeline_years') or 0) or 0)
        except (TypeError, ValueError):
            years_num = 0
        if years_num <= 0 and total_months >= 12:
            years_num = round(total_months / 12)
        # Fractional derived years are a storage detail — the strip shows whole years or none.
        years_text = str(int(years_num)) if years_num >= 1 and float(years_num).is_integer() else (
            str(round(years_num, 1)) if years_num >= 1 else '')
        start_str = phases[0].get('start_label') or (
            f"سنة {phases[0].get('year')} ({phases[0].get('quarter')})" if phases and phases[0].get('year') else '—')
        end_str = phases[-1].get('end_label') or (
            f"سنة {phases[-1].get('endYear')} ({phases[-1].get('endQuarter')})" if phases and phases[-1].get('endYear') else '—')
        if total_months:
            duration_str = f"{total_months} شهر" + (f" ({years_text} سنوات)" if years_text else '')
        else:
            duration_str = f"{years_text} سنوات" if years_text else '—'

    stats_cards = [
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">المدة الكلية للمشروع</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(duration_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">تاريخ انطلاق الأعمال</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(start_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">التسليم والتشغيل المتوقع</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(end_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">المراحل التنفيذية المعتمدة</div>'
        f'<div style="font-size:15px;font-weight:800;color:{accent};margin-top:2px;">{len(phases)} مراحل رئيسية</div></div>',
    ]
    stats_strip_html = f'<div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:14px;margin-bottom:18px;">{"".join(stats_cards)}</div>'

    if axis:
        palette = []
        for color in (primary, accent, secondary,
                      _mix_hex_colors(primary, accent, 0.55),
                      _mix_hex_colors(primary, secondary, 0.6),
                      _mix_hex_colors(secondary, accent, 0.45)):
            if color and color not in palette:
                palette.append(color)
        pipeline_html = _timeline_gantt_html(
            axis[0], axis[1], sorted_dated, undated, palette, primary, accent)
    else:
        num_phases = len(phases)
        if num_phases <= 5:
            cards = []
            for idx, phase in enumerate(phases, 1):
                p_name = html_lib.escape(str(phase.get('name') or ''))
                p_dur = str(phase.get('duration') or '').strip()
                dur_badge = f'<span style="background:#f1f5f9;color:{primary};padding:3px 8px;border-radius:6px;font-size:11.5px;font-weight:700;border:1px solid #cbd5e1;">{p_dur} شهر</span>' if p_dur else ''
                p_start = phase.get('start_label') or (
                    f"سنة {phase.get('year')} ({phase.get('quarter')})" if phase.get('year') else '—')
                p_end = phase.get('end_label') or (
                    f"سنة {phase.get('endYear')} ({phase.get('endQuarter')})" if phase.get('endYear') else '—')
                p_notes = html_lib.escape(str(phase.get('notes') or '').strip())
                notes_html = f'<div style="font-size:11.5px;color:#475569;line-height:1.48;margin-top:10px;padding-top:8px;border-top:1px dashed #e2e8f0;">{p_notes}</div>' if p_notes else ''

                card = f'''<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 14px;display:flex;flex-direction:column;justify-content:space-between;box-sizing:border-box;position:relative;border-top:5px solid {accent if idx % 2 == 1 else primary};">
                  <div>
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                      <span style="font-size:11px;font-weight:800;color:#94a3b8;">المرحلة 0{idx}</span>
                      {dur_badge}
                    </div>
                    <div style="font-size:14.5px;font-weight:800;color:{primary};line-height:1.4;margin-bottom:10px;min-height:40px;">{p_name}</div>
                    <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#334155;line-height:1.5;">
                      <div><strong style="color:#64748b;">من:</strong> {html_lib.escape(str(p_start))}</div>
                      <div style="margin-top:2px;"><strong style="color:#64748b;">إلى:</strong> {html_lib.escape(str(p_end))}</div>
                    </div>
                  </div>
                  {notes_html}
                </div>'''
                cards.append(card)
            pipeline_html = f'<div style="display:grid;grid-template-columns:repeat({max(1, num_phases)}, 1fr);gap:12px;height:380px;">{"".join(cards)}</div>'
        else:
            cards = []
            for idx, phase in enumerate(phases, 1):
                p_name = html_lib.escape(str(phase.get('name') or ''))
                p_dur = str(phase.get('duration') or '').strip()
                dur_text = f"{p_dur} شهر" if p_dur else ''
                p_start = phase.get('start_label') or (
                    f"سنة {phase.get('year')} ({phase.get('quarter')})" if phase.get('year') else '—')
                p_end = phase.get('end_label') or (
                    f"سنة {phase.get('endYear')} ({phase.get('endQuarter')})" if phase.get('endYear') else '—')
                p_notes = html_lib.escape(str(phase.get('notes') or '').strip())
                card = f'''<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;border-right:4px solid {primary};">
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span style="font-size:13.5px;font-weight:800;color:{primary};">المرحلة 0{idx}: {p_name}</span>
                    <span style="font-size:11.5px;font-weight:700;color:#64748b;">{dur_text} ({p_start} — {p_end})</span>
                  </div>
                  {f'<div style="font-size:11px;color:#475569;margin-top:4px;">{p_notes}</div>' if p_notes else ''}
                </div>'''
                cards.append(card)
            pipeline_html = f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;max-height:380px;overflow:hidden;">{"".join(cards)}</div>'

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">TIMELINE & DEVELOPMENT</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">المراحل التنفيذية والمدد الزمنية المتوقعة لتطوير وإنجاز المشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    {stats_strip_html}
    {pipeline_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">الجدول الزمني ومراحل المشروع</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''
