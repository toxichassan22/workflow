

def _fallback_table_data(slide, project_data):
    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    source = str((slide or {}).get('content_source') or '')
    chart_source = _financial_chart_source(slide, model) if source.startswith('financial_table:') else None
    if chart_type == 'combo':
        c_data = _extract_combo_chart_data(chart_source, model, project_data)
        items = c_data.get('items') or []
        if items:
            headers = ['السنة', 'صافي التدفق السنوي', 'الرصيد التراكمي']
            rows = [[it.get('year', ''), it.get('net_flow_full', it.get('net_flow_display', '')), it.get('cumulative_full', it.get('cumulative_display', ''))] for it in items]
            return headers, rows
    elif chart_type == 'waterfall':
        w_data = _extract_waterfall_chart_data(chart_source, model, project_data)
        items = w_data.get('items') or []
        if items:
            headers = ['بند التكلفة', 'القيمة (ر.س)']
            rows = [[it.get('name', ''), f"{it.get('value_sar', 0):,.0f} ر.س" if it.get('value_sar') else it.get('display', '')] for it in items]
            if w_data.get('total'):
                rows.append([w_data['total'].get('name', 'الإجمالي'), f"{w_data['total'].get('value_sar', 0):,.0f} ر.س" if w_data['total'].get('value_sar') else w_data['total'].get('display', '')])
            return headers, rows
    elif chart_type == 'heatmap':
        h_data = _extract_heatmap_chart_data(chart_source, model, project_data)
        matrix = h_data.get('matrix') or []
        if matrix:
            headers = ['المؤشر المالي', 'متحفظ', 'أساسي', 'متفائل']
            rows = [[r.get('metric', ''), r.get('conservative', ''), r.get('base', ''), r.get('optimistic', '')] for r in matrix]
            return headers, rows

    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
            return part.get('headers') or ['البند', 'القيمة'], part.get('rows') or []
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        name = 'التكاليف والاستثمار' if key == 'costs' else 'مؤشرات العائد والاسترداد'
        return ['البند', 'القيمة'], _financial_summary_from_report(model).get(name, [])[start:end]
    if source == 'financial_indicators':
        # The closing financial summary when the report carries no dedicated
        # cost/return groups. Render the study's own key figures (same labels
        # as the PDF note) instead of an empty table.
        projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
        inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
        calc = _parse_financial_dict(project_data.get('financial_calc_data'))
        indicator_rows = []
        for key, label in _FINANCIAL_INDICATOR_LABELS:
            value = projection.get(key)
            if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
                value = inputs.get(key)
            if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
                value = calc.get(key)
            if value in (None, '', [], {}, -1):
                continue
            indicator_rows.append([label, value])
            if len(indicator_rows) >= 12:
                break
        return ['البند', 'القيمة'], indicator_rows
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(key) if isinstance(tables.get(key), list) else []
        if not rows:
            aliases = {
                'cashflowTable': ('cashflow',),
                'sensitivityTable': ('sensitivity',),
                'sensitivityAssumptionsTable': ('sensitivity',),
            }
            rows = next((tables.get(alias) for alias in aliases.get(key, ())
                         if isinstance(tables.get(alias), list)), [])
        if not rows and key == 'componentsTable':
            rows = _project_component_rows(project_data)
        selected = rows[start:end]
        if selected and isinstance(selected[0], dict):
            headers = [k for k in selected[0].keys() if str(k).strip() not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions', 'id', 'row_id', 'الناتج')]
            active_headers = []
            for h in headers:
                vals = [str(row.get(h) or '').strip() for row in selected]
                has_content = any(v and v not in ('0', '0.0', '—', '-', '0%', '0.00') for v in vals)
                if has_content or len(active_headers) == 0:
                    active_headers.append(h)
            if active_headers:
                headers = active_headers
            return headers, [[row.get(header, '') for header in headers] for row in selected]
        return [], selected
    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        rows = _project_component_rows(project_data)[start:end]
        headers = list(rows[0].keys()) if rows else []
        return headers, [[row.get(header, '') for header in headers] for row in rows]
    if source == 'market_study_data.scope' or (slide or {}).get('source_table') == 'market_scope':
        market = _market_state(project_data)
        rows = _market_scope_rows(market)
        return ['البند', 'القيمة'], rows
    summary_match = re.fullmatch(r'market_study_data\.summary(?::(\d+):(\d+))?', source)
    if summary_match or (slide or {}).get('source_table') == 'market_summary':
        market = _market_state(project_data)
        rows, _row_offset = _market_rows_for_slide(
            slide, 'market_study_data.summary', _market_summary_rows(market)
        )
        return ['محور التحليل', 'الملخص المعتمد'], rows
    sources_match = re.fullmatch(r'market_study_data\.sources(?::(\d+):(\d+))?', source)
    if sources_match or (slide or {}).get('source_table') == 'market_sources':
        market = _market_state(project_data)
        rows, _row_offset = _market_rows_for_slide(
            slide, 'market_study_data.sources', _market_source_rows(market)
        )
        return ['المصدر', 'الرابط', 'تاريخ البيانات', 'تاريخ الوصول', 'الموثوقية', 'الملاحظات'], rows
    if source == 'market_study_data.competitors' or (slide or {}).get('source_table') == 'competitors' or 'competitors' in source:
        market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        competitors = [c for c in competitors if isinstance(c, dict) and _competitor_name(c)]
        c_start = (slide or {}).get('competitor_start')
        c_end = (slide or {}).get('competitor_end')
        cs = str(source or '')
        if c_start is not None and c_end is not None:
            competitors = competitors[c_start:c_end]
        elif ':' in cs:
            parts = cs.split(':')
            if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                competitors = competitors[int(parts[-2]):int(parts[-1])]
        chart_items = _extract_competitor_chart_data(competitors, project_data)
        if chart_items:
            headers = ['المنافس / المشروع', 'السعر', 'النوع']
            rows = [[it.get('name', ''), it.get('display_price', ''), it.get('price_type', '')] for it in chart_items]
            return headers, rows
    if source == 'timeline_table_data' or (slide or {}).get('design_style') == 'timeline':
        phases = parse_timeline_phases(project_data)
        if phases:
            headers = ['المرحلة', 'البداية', 'المدة (أشهر)', 'النهاية', 'الملاحظات']
            rows = [
                [
                    p.get('name', ''),
                    p.get('start_label') or f"سنة {p.get('year', '')} ({p.get('quarter', '')})",
                    p.get('duration', ''),
                    p.get('end_label') or f"سنة {p.get('endYear', '')} ({p.get('endQuarter', '')})",
                    p.get('notes', ''),
                ]
                for p in phases
            ]
            return headers, rows
    if source == 'land_specs' or (slide or {}).get('design_style') == 'specs':
        specs = _extract_land_specs_data(project_data)
        labels = {
            'deed_number': 'رقم الصك',
            'deed_date': 'تاريخ الصك',
            'plan_number': 'رقم المخطط',
            'plot_number': 'رقم القطعة',
            'land_area': 'مساحة الأرض',
            'built_area': 'مساحة البناء',
            'building_ratio_coverage': 'نسبة البناء والتغطية',
            'far': 'معامل البناء (FAR)',
            'setbacks': 'الارتدادات النظامية',
            'max_floors_height': 'الحد الأقصى للارتفاع / الأدوار',
            'allowed_uses': 'الاستخدامات المصرحة',
            'building_system': 'نظام البناء والاشتراطات',
            'parking_regulations': 'اشتراطات المواقف',
            'infrastructure': 'البنية التحتية والخدمات',
        }
        headers = ['البند التنظيمي / المساحي', 'المحدد المعتمد']
        rows = [[label, specs.get(k, '—')] for k, label in labels.items() if specs.get(k) and specs.get(k) != '—']
        return headers, rows
    return [], []


def _format_table_num(val):
    s = str(val or '').strip()
    if not s or s in ('—', '-', 'N/A', 'nan'):
        return '—', False
    if re.match(r'^-?\d{1,3}(,\d{3})+(\.\d+)?%?$', s):
        return s, True
    is_pct = s.endswith('%')
    raw_num = s[:-1].strip() if is_pct else s
    try:
        clean = raw_num.replace(',', '')
        f = float(clean)
        if 1950 <= f <= 2050 and '.' not in raw_num and not is_pct:
            return str(int(f)), True
        if abs(f) >= 1000 and '.' not in raw_num:
            res = f"{int(f):,}"
        elif abs(f) >= 1000:
            res = f"{f:,.2f}".rstrip('0').rstrip('.')
        else:
            res = raw_num
        if is_pct:
            res += '%'
        return res, True
    except (ValueError, TypeError):
        return html_lib.escape(s), False


def _render_fallback_table(headers, rows, primary):
    n_rows = len(rows)
    if n_rows >= 12:
        th_pad = '5px 8px'
        th_font = '11px'
        td_pad = '4px 6px'
        td_font = '10px'
    elif n_rows >= 8:
        th_pad = '6px 10px'
        th_font = '11.5px'
        td_pad = '5px 8px'
        td_font = '10.5px'
    else:
        th_pad = '9px 12px'
        th_font = '12px'
        td_pad = '8px 12px'
        td_font = '11.5px'

    header_html = ''.join(
        f'<th style="background:{primary};color:#fff;padding:{th_pad};font-size:{th_font};text-align:center;vertical-align:middle;">{html_lib.escape(str(value))}</th>'
        for value in headers)
    body = []
    for row_idx, row in enumerate(rows):
        values = list(row.values()) if isinstance(row, dict) else list(row) if isinstance(row, (list, tuple)) else [row]
        bg = '#f8fafc' if row_idx % 2 == 1 else '#ffffff'
        tds = []
        for col_idx, val in enumerate(values):
            fmt, is_num = _format_table_num(val)
            direction = 'ltr' if is_num else 'rtl'
            tds.append(
                f'<td style="border-bottom:1px solid #e2e8f0;padding:{td_pad};font-size:{td_font};'
                f'text-align:center;direction:{direction};vertical-align:middle;font-feature-settings:\'tnum\';font-variant-numeric:tabular-nums;">{fmt}</td>'
            )
        body.append(f'<tr style="background:{bg};">{"".join(tds)}</tr>')
    return ('<table data-preserve-density="1" style="width:100%;border-collapse:collapse;table-layout:fixed;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">'
            f'<thead><tr>{header_html}</tr></thead><tbody>{"".join(body)}</tbody></table>')


def _competitor_table_cell(value, fallback='—'):
    text = _competitor_display_text(value, fallback=fallback)
    formatted, is_num = _format_table_num(text)
    return formatted if is_num else html_lib.escape(text)


def _competitor_area_display(comp):
    area_cache = comp.get('area_cache') if isinstance(comp, dict) and isinstance(comp.get('area_cache'), dict) else {}
    area_fixed = _competitor_value(comp, 'area_sqm', 'area', 'المساحة') or area_cache.get('area_sqm')
    area_from = _competitor_value(comp, 'area_from', 'min_area', 'من') or area_cache.get('area_from')
    area_to = _competitor_value(comp, 'area_to', 'max_area', 'إلى') or area_cache.get('area_to')
    area_mode = str(_competitor_value(comp, 'area_mode', 'mode') or '').strip().lower()
    if area_mode == 'range' or area_from not in (None, '', []) or area_to not in (None, '', []):
        return f'من {_competitor_table_cell(area_from)} إلى {_competitor_table_cell(area_to)}'
    return _competitor_table_cell(area_fixed)


def _competitor_source_display(comp):
    """The sources column carries numbered source links only — no extra prose."""
    urls = comp.get('source_urls') if isinstance(comp, dict) and isinstance(comp.get('source_urls'), list) else []
    if not urls:
        single_url = _competitor_value(comp, 'source_url')
        urls = [single_url] if single_url else []
    links = []
    for index, url in enumerate(urls, 1):
        url_text = str(url or '').strip()
        if re.match(r'^https?://', url_text, re.IGNORECASE):
            links.append(
                f'<a href="{html_lib.escape(url_text, quote=True)}" target="_blank" rel="noopener noreferrer" '
                f'style="color:#2563eb;font-size:9px;">المصدر {index}</a>'
            )
    if not links:
        return '<div style="color:#94a3b8;">—</div>'
    return '<div style="display:flex;flex-direction:column;gap:3px;align-items:center;">' + ''.join(links) + '</div>'


def _render_competitor_table(competitors, primary):
    """Render every stored competitor field in one deterministic table."""
    named = [c for c in (competitors or []) if isinstance(c, dict) and _competitor_name(c)]
    roomy = len(named) <= 4
    logo_height = '54px' if roomy else '42px'
    cell_pad = '8px 4px' if roomy else '5px 4px'
    rows_html = []
    has_logo = False
    for index, comp in enumerate(competitors or [], 1):
        if not isinstance(comp, dict) or not _competitor_name(comp):
            continue
        name = _competitor_name(comp)
        logo_token = _competitor_logo_token(comp, index)
        has_logo = has_logo or bool(logo_token)
        if logo_token:
            logo_html = (
                f'<div style="height:{logo_height};display:flex;align-items:center;justify-content:center;">'
                f'<img src="{logo_token}" alt="{html_lib.escape(name, quote=True)}" '
                'style="width:76px;height:100%;object-fit:contain;background:#fff;border:1px solid #cbd5e1;border-radius:6px;padding:3px;box-sizing:border-box;">'
                '</div>'
            )
        else:
            logo_html = f'<div style="height:{logo_height};display:flex;align-items:center;justify-content:center;color:#64748b;">لا يوجد</div>'
        project_type = _competitor_value(comp, 'project_type', 'projectType', 'النوع')
        classification = _competitor_value(comp, 'classification', 'التصنيف')
        type_html = f'<div>{html_lib.escape(_competitor_display_text(project_type))}</div>'
        if classification:
            type_html += f'<div style="margin-top:2px;color:#64748b;font-size:8px;">{html_lib.escape(_competitor_display_text(classification))}</div>'
        operation = _competitor_value(comp, 'operation_type', 'operation', 'نوع العملية')
        status = _competitor_value(comp, 'status', 'الحالة')
        price = html_lib.escape(_competitor_price_display(comp))
        cells = (
            logo_html,
            html_lib.escape(name),
            type_html,
            _competitor_area_display(comp),
            _competitor_table_cell(status),
            _competitor_table_cell(operation),
            price,
            _competitor_source_display(comp),
        )
        bg = '#f8fafc' if len(rows_html) % 2 else '#ffffff'
        rows_html.append(
            f'<tr style="background:{bg};">' + ''.join(
                f'<td style="border-bottom:1px solid #e2e8f0;padding:{cell_pad};font-size:{"8.5px" if col_idx in (0, 7) else "9px"};'
                f'text-align:center;direction:rtl;vertical-align:middle;line-height:1.25;word-break:break-word;">{value}</td>'
                for col_idx, value in enumerate(cells)
            ) + '</tr>'
        )
    if not rows_html:
        return '<div data-competitor-table="1" style="padding:20px;text-align:center;color:#64748b;border:1px solid #e2e8f0;border-radius:6px;">لا توجد بيانات منافسين</div>'
    headers = ('الشعار', 'اسم المشروع', 'النوع والتصنيف', 'المساحة م²', 'الحالة', 'نوع العملية', 'بيانات السعر', 'المصادر')
    header_html = ''.join(
        f'<th style="background:{primary};color:#fff;padding:6px 4px;font-size:9px;text-align:center;vertical-align:middle;line-height:1.2;">{header}</th>'
        for header in headers
    )
    logo_attr = ' data-competitor-logos="1"' if has_logo else ''
    return (
        f'<table data-competitor-table="1"{logo_attr} data-preserve-density="1" '
        'style="width:100%;border-collapse:collapse;table-layout:fixed;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">'
        f'<colgroup><col style="width:12%"><col style="width:14%"><col style="width:14%"><col style="width:11%">'
        '<col style="width:9%"><col style="width:11%"><col style="width:15%"><col style="width:14%"></colgroup>'
        f'<thead><tr>{header_html}</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'
    )


def _render_fallback_horizontal_bar(items, primary='#005f78', secondary='#0ea5e9'):
    if not items:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات منافسين كافية</div>'
    grouped = len({it.get('group_key') for it in items if it.get('group_key')}) > 1
    many = len(items) > 5
    bar_height = '14px' if many else '20px'
    row_gap = '8px' if many else '14px'
    name_font = '11px' if many else '12px'
    price_font = '11px' if many else '12.5px'
    rows_html = []
    for it in items:
        if grouped and it.get('group_first') and it.get('group_label'):
            rows_html.append(
                f'<div style="margin-top:2px;padding-top:8px;border-top:1px dashed #cbd5e1;'
                f'font-size:10.5px;font-weight:800;color:{primary};letter-spacing:.2px;">'
                f'{html_lib.escape(str(it["group_label"]))}</div>'
            )
        name = html_lib.escape(str(it.get('name') or ''))
        width = it.get('bar_width_pct', 50.0)
        start = it.get('bar_start_pct', 0.0)
        display_price = html_lib.escape(str(it.get('display_price') or ''))
        is_project = bool(it.get('is_project'))
        bar_color = primary if is_project else secondary
        font_weight = '800' if is_project else '600'
        border_box = f'border: 2px solid {primary}; background: rgba(0, 95, 120, 0.06); padding: 8px 10px; border-radius: 6px;' if is_project else 'padding: 4px 0;'
        badge = f'<span style="background:{primary};color:#fff;font-size:10px;padding:2px 6px;border-radius:3px;margin-right:6px;">مشروعنا</span>' if is_project else ''
        rows_html.append(f'''
        <div style="display:flex;flex-direction:column;gap:5px;{border_box}">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:{name_font};">
                <span style="font-weight:{font_weight};color:#1e293b;">{badge}{name}</span>
                <span style="font-weight:700;color:{bar_color};font-size:{price_font};white-space:nowrap;">{display_price}</span>
            </div>
            <div style="width:100%;height:{bar_height};background:#e2e8f0;border-radius:3px;overflow:hidden;position:relative;">
                <div style="position:absolute;left:{start}%;width:{width}%;height:100%;background:{bar_color};border-radius:3px;"></div>
            </div>
        </div>
        ''')
    return (
        f'<div style="display:flex;flex-direction:column;gap:{row_gap};background:#f8fafc;padding:16px 18px;border-radius:8px;border:1px solid #e2e8f0;flex:1 1 auto;box-sizing:border-box;justify-content:center;">'
        f'<div style="font-size:13px;font-weight:700;color:{primary};border-bottom:1px solid #cbd5e1;padding-bottom:6px;">مقارنة أسعار المنافسين في السوق</div>'
        f'{"".join(rows_html)}'
        f'</div>'
    )


def _market_scope_display(market):
    if not isinstance(market, dict):
        return ''
    radius = market.get('competitor_radius')
    if radius == 'city':
        radius_text = 'كامل المدينة'
    elif radius == 'custom':
        radius_text = _competitor_display_text(market.get('competitor_radius_custom_km')) + ' كم'
    elif radius not in (None, ''):
        radius_text = _competitor_display_text(radius) + ' كم'
    else:
        radius_text = ''
    period_map = {
        '12m': 'آخر 12 شهرًا', '24m': 'آخر 24 شهرًا', '3y': 'آخر 3 سنوات', '5y': 'آخر 5 سنوات',
    }
    period = market.get('data_period')
    period_text = period_map.get(str(period), '') if period not in (None, '') else ''
    if period == 'custom':
        period_text = f'من {_competitor_display_text(market.get("data_period_from"))} إلى {_competitor_display_text(market.get("data_period_to"))}'
    parts = []
    if radius_text:
        parts.append(f'نطاق المنافسين: {radius_text}')
    if period_text:
        parts.append(f'فترة البيانات: {period_text}')
    return ' | '.join(parts)


def _market_chart_provenance(competitors):
    items = []
    for comp in competitors or []:
        if not isinstance(comp, dict):
            continue
        source = _competitor_display_text(_competitor_value(comp, 'source', 'المصدر'), '')
        data_date = _competitor_display_text(_competitor_value(comp, 'data_date', 'dataDate', 'source_date', 'date', 'تاريخ البيانات'), '')
        if source or data_date:
            text = source or 'مصدر موثق'
            if data_date:
                text += f'، تاريخ البيانات: {data_date}'
            if text not in items:
                items.append(text)
    if not items:
        return ''
    return 'مصدر ووقت بيانات المقارنة: ' + '؛ '.join(items)


def _render_fallback_waterfall(chart_data, primary='#005f78', secondary='#0ea5e9'):
    summary = (chart_data or {}).get('summary') if isinstance(chart_data, dict) else {}
    svg_code = summary.get('svg_code')
    if svg_code:
        return (
            f'<div style="background:#f8fafc;padding:14px 14px 20px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
            f'<div style="font-size:13px;font-weight:700;color:{primary};margin-bottom:8px;">تكوين إجمالي تكلفة المشروع (ملايين ر.س)</div>'
            f'{svg_code}'
            f'</div>'
        )
    items = (chart_data or {}).get('items') or []
    total = (chart_data or {}).get('total') or {}
    if not items and not total:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات تكاليف كافية</div>'
    cols_html = []
    for it in items:
        name = html_lib.escape(str(it.get('name') or ''))
        display = html_lib.escape(str(it.get('display') or ''))
        h = it.get('height_pct', 10.0)
        offset = it.get('offset_pct', 0.0)
        cols_html.append(f'''
        <div style="flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative;">
            <div style="position:absolute;bottom:{offset + h + 2}%;font-size:10px;font-weight:700;color:{primary};white-space:nowrap;">{display}</div>
            <div style="position:absolute;bottom:{offset}%;height:{h}%;width:75%;background:{secondary};border-radius:3px;border:1px solid rgba(0,0,0,0.08);"></div>
            <div style="position:absolute;top:100%;padding-top:6px;font-size:10px;font-weight:600;color:#475569;text-align:center;line-height:1.2;word-break:break-word;">{name}</div>
        </div>
        ''')
    if total:
        t_name = html_lib.escape(str(total.get('name') or 'إجمالي تكلفة المشروع'))
        t_display = html_lib.escape(str(total.get('display') or ''))
        t_h = total.get('height_pct', 100.0)
        cols_html.append(f'''
        <div style="flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative;">
            <div style="position:absolute;bottom:{t_h + 2}%;font-size:11px;font-weight:800;color:{primary};white-space:nowrap;">{t_display}</div>
            <div style="position:absolute;bottom:0;height:{t_h}%;width:85%;background:{primary};border-radius:3px;border:1px solid rgba(0,0,0,0.1);"></div>
            <div style="position:absolute;top:100%;padding-top:6px;font-size:10px;font-weight:700;color:{primary};text-align:center;line-height:1.2;word-break:break-word;">{t_name}</div>
        </div>
        ''')
    return (
        f'<div style="background:#f8fafc;padding:16px 14px 44px;border-radius:8px;border:1px solid #e2e8f0;display:flex;flex-direction:column;gap:10px;">'
        f'<div style="font-size:13px;font-weight:700;color:{primary};">تكوين إجمالي تكلفة المشروع (ملايين ر.س)</div>'
        f'<div style="height:230px;display:flex;align-items:flex-end;justify-content:space-between;border-bottom:2px solid #94a3b8;position:relative;gap:6px;">'
        f'{"".join(cols_html)}'
        f'</div>'
        f'</div>'
    )


def _render_fallback_combo(chart_data, primary='#005f78', secondary='#0ea5e9'):
    summary = (chart_data or {}).get('summary') if isinstance(chart_data, dict) else {}
    svg_code = summary.get('svg_code')
    if svg_code:
        return (
            f'<div style="background:#f8fafc;padding:14px 14px 20px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            f'<span style="font-size:12px;font-weight:700;color:{primary};">التدفقات النقدية السنوية والتراكمية (ملايين ر.س)</span>'
            f'<div style="display:flex;gap:12px;font-size:9.5px;font-weight:600;">'
            f'<span style="color:#0b1f33;">صافي التدفق السنوي</span>'
            f'<span style="color:#b89564;">تدفق سالب</span>'
            f'<span style="color:#0284c7;">الرصيد التراكمي</span>'
            f'</div>'
            f'</div>'
            f'{svg_code}'
            f'</div>'
        )
    items = (chart_data or {}).get('items') if isinstance(chart_data, dict) else chart_data
    if not items:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات تدفقات نقدية كافية</div>'
    items = items[:15]
    cols_html = []
    points = []
    net_flows = [it.get('net_flow_m', 0.0) for it in items]
    cums = [it.get('cumulative_m', 0.0) for it in items]
    max_flow = max([abs(f) for f in net_flows] + [1.0])
    min_cum = min(cums + [0.0])
    max_cum = max(cums + [1.0])
    cum_range = (max_cum - min_cum) or 1.0

    for idx, it in enumerate(items):
        year = html_lib.escape(str(it.get('year') or f'سنة {idx+1}'))
        flow = it.get('net_flow_m', 0.0)
        cum = it.get('cumulative_m', 0.0)
        is_pos = flow >= 0
        color = '#10b981' if is_pos else '#ef4444'
        bar_h = min(round((abs(flow) / max_flow) * 42, 1), 42.0)
        pos_bottom = '50%' if is_pos else f'{50 - bar_h}%'
        cols_html.append(f'''
        <div style="flex:1;height:100%;position:relative;display:flex;justify-content:center;">
            <div style="position:absolute;bottom:{pos_bottom};height:{bar_h}%;width:55%;background:{color};border-radius:2px;"></div>
            <div style="position:absolute;bottom:-24px;font-size:9px;font-weight:600;color:#64748b;white-space:nowrap;">{year}</div>
        </div>
        ''')
        x = round(30 + idx * (440 / max(len(items) - 1, 1)), 1)
        y = round(160 - ((cum - min_cum) / cum_range) * 120, 1)
        points.append((x, y))

    poly_pts = ' '.join(f'{x},{y}' for x, y in points)
    dots_svg = ''.join(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{primary}" stroke="#ffffff" stroke-width="1.5" />' for x, y in points)

    return (
        f'<div style="background:#f8fafc;padding:14px 14px 36px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
        f'<span style="font-size:12px;font-weight:700;color:{primary};">التدفقات النقدية السنوية والتراكمية</span>'
        f'<div style="display:flex;gap:10px;font-size:9px;font-weight:600;">'
        f'<span style="color:#10b981;">تدفق موجب</span>'
        f'<span style="color:#ef4444;">تدفق سالب</span>'
        f'<span style="color:{primary};">الرصيد التراكمي</span>'
        f'</div>'
        f'</div>'
        f'<div style="height:170px;position:relative;border-bottom:1px solid #cbd5e1;">'
        f'<div style="position:absolute;top:50%;left:0;right:0;border-top:1px dashed #94a3b8;z-index:1;"></div>'
        f'<div style="display:flex;height:100%;position:relative;z-index:2;">'
        f'{"".join(cols_html)}'
        f'</div>'
        f'<svg viewBox="0 0 500 170" style="position:absolute;inset:0;width:100%;height:100%;z-index:3;pointer-events:none;" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{primary}" stroke-width="2.5" points="{poly_pts}" stroke-linejoin="round" />'
        f'{dots_svg}'
        f'</svg>'
        f'</div>'
        f'</div>'
    )


def _render_fallback_heatmap(chart_data, primary='#005f78', secondary='#0ea5e9'):
    return _build_heatmap_matrix_html(chart_data, primary, secondary)


def _render_fallback_chart(chart_type, slide, project_data, primary='#005f78', secondary='#0ea5e9'):
    chart_type = canonicalize_chart_type(chart_type)
    if not chart_type:
        return ''
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    if chart_type == 'horizontal_bar':
        market = _decode_json_fact((project_data or {}).get('market_study_data')) if isinstance((project_data or {}).get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        competitors = [c for c in competitors if isinstance(c, dict) and _competitor_name(c)]
        c_start = (slide or {}).get('competitor_start')
        c_end = (slide or {}).get('competitor_end')
        cs = str((slide or {}).get('content_source') or '')
        if c_start is not None and c_end is not None:
            competitors = competitors[c_start:c_end]
        elif ':' in cs:
            parts = cs.split(':')
            if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                competitors = competitors[int(parts[-2]):int(parts[-1])]
        items = _extract_competitor_chart_data(competitors, project_data)
        return _render_fallback_horizontal_bar(items, primary, secondary)
    elif chart_type == 'waterfall':
        c_data = _extract_waterfall_chart_data(None, model, project_data)
        return _render_fallback_waterfall(c_data, primary, secondary)
    elif chart_type == 'combo':
        c_data = _extract_combo_chart_data(None, model, project_data)
        return _render_fallback_combo(c_data, primary, secondary)
    elif chart_type == 'heatmap':
        c_data = _extract_heatmap_chart_data(None, model, project_data)
        return _render_fallback_heatmap(c_data, primary, secondary)
    return ''


SOL_SLIDES_CSS = """
  .slide {
    width: 1280px; height: 720px; position: relative; overflow: hidden;
    background: #ffffff; color: #0b1f33; box-sizing: border-box; font-family: inherit;
  }
  /* NOTE: no .slide-header/.slide-footer rules live here on purpose. The SOL
     builders below emit their own header/footer markup, but postprocess_slide()
     always replaces it with the single canonical chrome, so class-based header
     rules would only restyle that chrome in renderers that drop inline styles.
     Body components (tables, KPIs, charts) are styled below. */
  .luxury-kpi-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 16px;
  }
  .luxury-kpi-card {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .luxury-kpi-card.primary {
    background: #0b1f33; border-color: #0b1f33; color: #ffffff;
  }
  .luxury-kpi-card.primary .kpi-label { color: #94a3b8; }
  .luxury-kpi-card.primary .kpi-val { color: #ffffff; }
  .luxury-kpi-card.accent {
    border-right: 3px solid #c59a58;
  }
  .kpi-label { font-size: 11px; font-weight: 600; color: #64748b; margin-bottom: 4px; }
  .kpi-val { font-size: 20px; font-weight: 800; color: #0b1f33; font-feature-settings: "tnum"; font-variant-numeric: tabular-nums; }

  .financial-table-wrap {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;
  }
  .financial-table {
    width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: center;
  }
  .financial-table th {
    background: #0b1f33; color: #ffffff; font-weight: 700; padding: 10px 14px; font-size: 11.5px; white-space: nowrap; text-align: center; vertical-align: middle;
  }
  .financial-table td {
    padding: 8px 14px; border-bottom: 1px solid #f1f5f9; color: #1e293b; font-weight: 500; text-align: center; vertical-align: middle;
  }
  .financial-table tr:nth-child(even) td {
    background: #f8fafc;
  }
  .financial-table td.numeric {
    text-align: center !important; vertical-align: middle; direction: ltr; font-weight: 600; font-feature-settings: "tnum"; font-variant-numeric: tabular-nums;
  }
  .financial-table tfoot td {
    background: #f1f5f9; font-weight: 800; border-top: 2px solid #cbd5e1; color: #0b1f33;
  }
  .stacked-financial-tables .financial-table th {
    padding: 6px 10px; font-size: 11px;
  }
  .stacked-financial-tables .financial-table td {
    padding: 5px 10px; font-size: 11px;
  }

  .waterfall-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px 24px;
    height: 420px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between;
  }
  .waterfall-card-header {
    display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9;
  }
  .waterfall-card-title { font-size: 14px; font-weight: 700; color: #0b1f33; }
  .waterfall-card-unit { font-size: 11px; font-weight: 600; color: #64748b; }

  .cashflow-layout {
    display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 18px; align-items: start;
  }
  .combo-chart-box {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px;
  }
  .table-note {
    font-size: 10.5px; color: #94a3b8; margin-top: 8px; font-weight: 500;
  }
"""


def _build_sol_waterfall_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تكوين إجمالي تكلفة المشروع'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    w_data = _extract_waterfall_chart_data(_financial_chart_source(slide, model), model, source)
    items = w_data.get('items') or []
    total = w_data.get('total') or {}

    total_cost_m = total.get('value_millions', 0.0)
    total_cost_display = total.get('display', f"{total_cost_m:,.2f} ر.س")
    sorted_items = sorted(items, key=lambda x: x.get('value_millions', 0), reverse=True)
    top2_pct = sum(it.get('pct_of_total', 0) for it in sorted_items[:2]) if sorted_items else 0
    top1_name = sorted_items[0].get('name', 'المكون الرئيسي') if sorted_items else 'المكون الرئيسي'
    top1_val = sorted_items[0].get('display', '—') if sorted_items else '—'

    waterfall_rows = [
        [it.get('name', ''), f"{it.get('value_sar', 0):,.0f} ر.س" if it.get('value_sar') else it.get('display', ''), f"{it.get('pct_of_total', 0):.1f}%"]
        for it in items
    ]
    if total:
        tot_val_sar = total.get('value_sar', 0)
        tot_val_display = f"{tot_val_sar:,.0f} ر.س" if tot_val_sar else total.get('display', '')
        waterfall_rows.append([
            total.get('name', 'إجمالي تكلفة المشروع'),
            tot_val_display,
            '100%',
        ])
    waterfall_table = _render_fallback_table(
        ['بند التكلفة', 'القيمة (ر.س)', 'النسبة'], waterfall_rows, primary)

    # Use width=580, height=350 to fit the 0.95fr / 1.05fr grid layout cleanly
    svg_code = _build_waterfall_svg(items, total, width=580, height=350, primary=primary, secondary='#0ea5e9', gold=accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">PROJECT COST WATERFALL</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مخطط شلالي يوضح مساهمة كل مكون في بناء إجمالي التكلفة الرأسمالية للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:70px;">
    <div class="luxury-kpi-grid" style="margin-bottom:12px;">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">إجمالي تكلفة المشروع</div>
        <div class="kpi-val">{total_cost_display}</div>
      </div>
      <div class="luxury-kpi-card accent" style="border-right-color:{accent};">
        <div class="kpi-label">المكونان الرئيسيان</div>
        <div class="kpi-val">{top2_pct:.1f}%</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">{top1_name}</div>
        <div class="kpi-val">{top1_val}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:0.95fr 1.05fr;gap:16px;height:440px;align-items:stretch;">
      <div class="financial-table-wrap" style="height:440px;overflow:hidden;border:1px solid #e2e8f0;border-radius:8px;">
        <div style="padding:10px 14px;font-size:13px;font-weight:700;color:{primary};border-bottom:1px solid #f1f5f9;background:#f8fafc;">جدول بنود التكلفة</div>
        {waterfall_table}
      </div>
      <div class="waterfall-card" style="height:440px;padding:14px 18px;">
        <div class="waterfall-card-header">
          <div class="waterfall-card-title" style="color:{primary};">المخطط الشلالي لتراكم التكلفة</div>
          <div class="waterfall-card-unit">القيم بمليون ر.س</div>
        </div>
        <div style="flex:1;display:flex;align-items:center;justify-content:center;margin-top:6px;">
          {svg_code}
        </div>
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">هيكل تكلفة المشروع — عرض تراكمي لمكونات التطوير</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_combo_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'التدفقات النقدية وصافي الرصيد التراكمي'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    c_data = _extract_combo_chart_data(_financial_chart_source(slide, model), model, source)
    items = c_data.get('items') or []
    summary = c_data.get('summary') or {}

    total_inflow = summary.get('total_inflow_display', '—')
    peak_outflow = summary.get('peak_outflow_display', '—')
    payback_year = summary.get('payback_year_display', '—')

    if (total_inflow == '—' or total_inflow.endswith(' 0.0 ر.س')) and items:
        tot_inf = sum(it.get('net_flow_m', 0) for it in items if it.get('net_flow_m', 0) > 0)
        total_inflow = f"{tot_inf:,.1f} مليون ر.س"
    if peak_outflow == '—' and items:
        min_cum = min((it.get('cumulative_m', 0) for it in items), default=0)
        peak_outflow = f"{abs(min_cum):,.1f} مليون ر.س"
    if payback_year == '—' and items:
        for it in items:
            if it.get('cumulative_m', 0) > 0:
                payback_year = str(it.get('year') or '')
                break

    table_rows = []
    for it in items:
        y = html_lib.escape(str(it.get('year') or ''))
        f_val = it.get('net_val') if 'net_val' in it else (it.get('net_flow_m', 0.0) * 1e6)
        c_val = it.get('cum_val') if 'cum_val' in it else (it.get('cumulative_m', 0.0) * 1e6)
        f_str = f"({abs(f_val):,.0f})" if f_val < 0 else f"{f_val:,.0f}"
        c_str = f"({abs(c_val):,.0f})" if c_val < 0 else f"{c_val:,.0f}"
        f_style = 'color:#dc2626;' if f_val < 0 else 'color:#059669;'
        c_style = 'color:#dc2626;' if c_val < 0 else f'color:{primary};'
        table_rows.append(f'''<tr>
          <td style="font-weight:600;text-align:center;vertical-align:middle;">{y}</td>
          <td class="numeric" style="{f_style}font-weight:700;text-align:center;vertical-align:middle;">{f_str}</td>
          <td class="numeric" style="{c_style}font-weight:700;text-align:center;vertical-align:middle;">{c_str}</td>
        </tr>''')

    svg_code = summary.get('svg_code') or _render_fallback_combo(c_data, primary, accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">CASH FLOW ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">تحليل التدفقات السنوية وصافي الرصيد التراكمي لسنوات المشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:70px;">
    <div class="luxury-kpi-grid" style="margin-bottom:12px;">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">إجمالي التدفقات الإيجابية</div>
        <div class="kpi-val">{total_inflow}</div>
      </div>
      <div class="luxury-kpi-card accent" style="border-right-color:{accent};">
        <div class="kpi-label">أقصى عجز تمويلي تراكمي</div>
        <div class="kpi-val">{peak_outflow}</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">سنة التحول للإيجابية / الاسترداد</div>
        <div class="kpi-val">{payback_year}</div>
      </div>
    </div>
    <div class="cashflow-layout" style="grid-template-columns:1.05fr 0.95fr;gap:16px;">
      <div class="financial-table-wrap" style="height:440px;overflow:hidden;">
        <table class="financial-table" data-preserve-density="1">
          <thead>
            <tr>
              <th style="background:{primary};text-align:center;vertical-align:middle;">السنة</th>
              <th style="background:{primary};text-align:center;vertical-align:middle;">صافي التدفق (ر.س)</th>
              <th style="background:{primary};text-align:center;vertical-align:middle;">الرصيد التراكمي (ر.س)</th>
            </tr>
          </thead>
          <tbody>
            {"".join(table_rows)}
          </tbody>
        </table>
      </div>
      <div class="combo-chart-box" style="height:440px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;padding:14px 18px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span style="font-size:13px;font-weight:700;color:{primary};">الرسم البياني للتدفقات</span>
          <div style="display:flex;gap:12px;font-size:10px;font-weight:600;">
            <span style="color:#059669;">تدفق موجب</span>
            <span style="color:#dc2626;">تدفق سالب</span>
            <span style="color:{primary};">التراكمي</span>
          </div>
        </div>
        <div style="flex:1;display:flex;align-items:center;justify-content:center;">
          {svg_code}
        </div>
        <div style="font-size:10px;color:#94a3b8;text-align:center;margin-top:6px;">القيم ممثلة بمليون ريال سعودي وفق الجدول الزمني المعتمد للمشروع</div>
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">التدفقات النقدية — صافي التدفق والرصيد التراكمي</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_table_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'جدول البيانات'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    headers, rows = _fallback_table_data(slide, source)
    if not rows:
        headers = ['البند', 'القيمة']
        rows = [['لا تتوفر بيانات', '—']]

    n_rows = len(rows)
    is_wide = len(headers) >= 8
    is_super_wide = len(headers) >= 12

    if n_rows <= 8:
        th_pad = '10px 14px'
        td_pad = '9px 14px'
        th_font = '12px'
        td_font = '12px'
    elif n_rows <= 14:
        th_pad = '8px 12px'
        td_pad = '6.5px 12px'
        th_font = '11.5px'
        td_font = '11px'
    else:
        th_pad = '6px 10px'
        td_pad = '4.5px 10px'
        th_font = '10.5px'
        td_font = '10px'

    if is_wide:
        th_pad = '6px 6px'
        td_pad = '5px 6px'
        th_font = '9.5px'
        td_font = '9px'

    if is_super_wide:
        th_pad = '5px 3px'
        td_pad = '4px 3px'
        th_font = '8.5px'
        td_font = '8px'

    th_cells = ''.join(f'<th style="background:{primary};color:#fff;font-weight:700;padding:{th_pad};font-size:{th_font};white-space:nowrap;text-align:center;vertical-align:middle;border-left:1px solid rgba(255,255,255,0.1);">{html_lib.escape(str(h))}</th>' for h in headers)
    
    tb_rows = []
    for r_idx, r in enumerate(rows):
        vals = list(r.values()) if isinstance(r, dict) else list(r) if isinstance(r, (list, tuple)) else [r]
        td_cells = []
        bg = '#f8fafc' if r_idx % 2 == 1 else '#ffffff'
        for idx, v in enumerate(vals):
            formatted, is_num = _format_table_num(v)
            num_color = ''
            if is_num:
                try:
                    raw_clean = str(v).replace(',', '').replace('%', '').strip()
                    num_val = float(raw_clean)
                    if num_val < 0:
                        num_color = 'color:#dc2626;'
                    elif num_val > 0 and idx == len(vals) - 1:
                        num_color = 'color:#059669;'
                except (ValueError, TypeError):
                    pass
            direction = 'ltr' if is_num else 'rtl'
            td_cells.append(f'<td style="padding:{td_pad};font-size:{td_font};text-align:center;vertical-align:middle;direction:{direction};border-bottom:1px solid #f1f5f9;word-break:break-word;overflow-wrap:anywhere;line-height:1.35;{num_color}font-weight:500;">{formatted}</td>')
        tb_rows.append(f'<tr style="background:{bg};">{"".join(td_cells)}</tr>')

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">FINANCIAL METRICS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">بيانات وجداول الدراسة المالية التفصيلية المعتمدة للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:70px;">
    <div class="financial-table-wrap" style="max-height:575px;overflow:hidden;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="padding:10px 18px;display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border-bottom:1px solid #e2e8f0;">
        <span style="font-size:13px;font-weight:700;color:{primary};">{title}</span>
        <span style="font-size:11px;font-weight:600;color:#64748b;background:#ffffff;padding:3px 10px;border-radius:12px;border:1px solid #e2e8f0;">عدد البنود: {n_rows}</span>
      </div>
      <table class="financial-table" data-preserve-density="1" style="width:100%;border-collapse:collapse;margin:0;">
        <thead>
          <tr>{th_cells}</tr>
        </thead>
        <tbody>
          {"".join(tb_rows)}
        </tbody>
      </table>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">{title}</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_heatmap_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'نتائج تحليل الحساسية'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    h_data = _extract_heatmap_chart_data(_financial_chart_source(slide, model), model, source)
    matrix_html = _build_heatmap_matrix_html(h_data, primary, accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    assumption_blocks = []
    assumption_sources = [str(value).strip() for value in (slide or {}).get('sensitivity_assumptions_sources', [])
                          if str(value or '').strip()]
    for assumption_source in assumption_sources:
        assumption_slide = dict(slide or {})
        assumption_slide['content_source'] = assumption_source
        assumption_slide['chart_type'] = ''
        headers, rows = _fallback_table_data(assumption_slide, source)
        if not rows:
            continue
        title_text = 'افتراضات تحليل الحساسية'
        table = _render_fallback_table(headers, rows, primary)
        assumption_blocks.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;overflow:hidden;">'
            f'<div style="font-size:14px;font-weight:800;color:{primary};margin-bottom:10px;text-align:right;">{title_text}</div>'
            f'<div style="max-height:390px;overflow:hidden;">{table}</div></div>'
        )
    sensitivity_side_content = matrix_html
    if assumption_blocks:
        sensitivity_side_content = (
            '<div style="display:grid;grid-template-columns:minmax(300px,0.78fr) minmax(0,1.22fr);'
            'gap:16px;align-items:start;max-height:440px;overflow:hidden;">'
            f'<div style="min-width:0;">{"".join(assumption_blocks)}</div>'
            f'<div style="min-width:0;overflow:hidden;">{matrix_html}</div>'
            '</div>'
        )

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">SENSITIVITY ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مصفوفة اختبار المؤشرات المالية وفق السيناريوهات الثلاثة (المتحفظ، الأساسي، المتفائل)</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:70px;">
    <div class="luxury-kpi-grid" style="margin-bottom:12px;">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">السيناريو الأساسي</div>
        <div class="kpi-val">النموذج المعتمد</div>
      </div>
      <div class="luxury-kpi-card accent" style="border-right-color:{accent};">
        <div class="kpi-label">السيناريو المتحفظ</div>
        <div class="kpi-val">اختبار الضغط</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">السيناريو المتفائل</div>
        <div class="kpi-val">أقصى كفاءة</div>
      </div>
    </div>
    <div style="max-height:510px;overflow:visible;">
      {sensitivity_side_content}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل الحساسية — مقارنة السيناريوهات الثلاثة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_horizontal_bar_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مقارنة أسعار المنافسين'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    market = _decode_json_fact(source.get('market_study_data')) if isinstance(source.get('market_study_data'), (str, dict)) else {}
    competitors = market.get('competitors') if isinstance(market, dict) else []
    competitors = [c for c in competitors if isinstance(c, dict) and _competitor_name(c)]
    c_start = (slide or {}).get('competitor_start')
    c_end = (slide or {}).get('competitor_end')
    cs = str((slide or {}).get('content_source') or '')
    if c_start is not None and c_end is not None:
        competitors = competitors[c_start:c_end]
    elif ':' in cs:
        parts = cs.split(':')
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            s_idx, e_idx = int(parts[-2]), int(parts[-1])
            competitors = competitors[s_idx:e_idx]

    items = _extract_competitor_chart_data(competitors, source)

    bar_chart_html = _render_fallback_horizontal_bar(items, primary, accent)
    table_html = _render_competitor_table(competitors, primary)
    scope_text = _market_scope_display(market)
    scope_html = (
        f'<div style="margin-bottom:10px;color:#64748b;font-size:10px;text-align:right;">'
        f'{html_lib.escape(scope_text)}</div>'
    ) if scope_text else ''
    provenance_text = _market_chart_provenance(competitors)
    provenance_html = (
        f'<div style="margin-top:8px;color:#64748b;font-size:9px;text-align:right;line-height:1.35;">'
        f'{html_lib.escape(provenance_text)}</div>'
    ) if provenance_text else ''
    stats_html = ''
    if items:
        first_key = items[0].get('group_key')
        first_items = [it for it in items if it.get('group_key') == first_key]
        lo = min((it['price_min_num'] for it in first_items), default=0.0)
        hi = max((it['price_max_num'] for it in first_items), default=0.0)
        unit_hint = first_items[0].get('display_price', '').split()[-1] if ' ' in first_items[0].get('display_price', '') else ''
        group_caption = items[0].get('group_label') or unit_hint
        range_text = f'من {lo:,.0f} إلى {hi:,.0f}' if hi > lo else f'{lo:,.0f}'
        stats_html = (
            f'<div style="margin-top:auto;padding-top:10px;display:flex;align-items:center;gap:16px;'
            f'font-size:10.5px;color:#475569;border-top:1px solid #e2e8f0;">'
            f'<span style="font-weight:800;color:{primary};">{len(competitors)} منافسًا معروضًا</span>'
            f'<span>نطاق {html_lib.escape(str(group_caption))}: {range_text}</span>'
            f'</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET BENCHMARK</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">تحليل أسعار السوق ومقارنة الوحدات المنافسة في النطاق الجغرافي</p>
      </div>
    </div>
  </header>
  <div style="padding:0 42px;margin-top:12px;">
    <div style="background:#f3f6f8;border:1px solid #dbe4ee;border-radius:12px;padding:14px 16px 16px;box-sizing:border-box;min-height:560px;display:flex;flex-direction:column;">
      {scope_html}
      <div style="display:grid;direction:rtl;grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:'table chart';gap:20px;flex:1;overflow:visible;align-items:stretch;">
      <div style="grid-area:table;background:#ffffff;border:1px solid #dbe4ee;border-radius:10px;padding:10px;overflow:visible;">
        {table_html}
      </div>
      <div style="grid-area:chart;background:#ffffff;border:1px solid #dbe4ee;border-radius:10px;padding:12px;overflow:visible;display:flex;flex-direction:column;">
        {bar_chart_html}
        {provenance_html}
        {stats_html}
      </div>
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">دراسة السوق — مقارنة أسعار المنافسين</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_stacked_tables_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    source = source if isinstance(source, dict) else {}
    lang = resolve_offer_lang(source)
    model = _parse_financial_dict(source.get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or section_title('financial', lang)))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    content_sources = (slide or {}).get('content_sources') or []

    table_blocks = []
    total_rows = 0
    for src in content_sources:
        dummy_slide = dict(slide)
        dummy_slide['content_source'] = src
        sub_headers, sub_rows = _fallback_table_data(dummy_slide, source)
        if sub_rows:
            total_rows += len(sub_rows)
            sub_title = ''
            match_sum = re.fullmatch(r'financial_summary:(costs|returns):\d+:\d+', src)
            if match_sum:
                if lang == OFFER_LANG_ENGLISH:
                    sub_title = 'Costs & Investment' if match_sum.group(1) == 'costs' else 'Return & Payback Indicators'
                else:
                    sub_title = 'التكاليف والاستثمار' if match_sum.group(1) == 'costs' else 'مؤشرات العائد والاسترداد'
            elif re.fullmatch(r'financial_table:([^:]+):\d+:\d+', src):
                t_key = re.fullmatch(r'financial_table:([^:]+):\d+:\d+', src).group(1)
                sub_title = next((t[1] for t in _financial_plan_tables(lang) if t[0] == t_key), t_key)
            elif re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', src):
                p_idx = int(re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', src).group(1))
                sub_title = _financial_report_part_title(model, p_idx)

            table_blocks.append((sub_title, tuple(str(h) for h in sub_headers), sub_rows, sub_headers))

    # Consecutive slices of one table (same title and columns) are merged as a single visual table
    merged_blocks = []
    for sub_title, headers_key, sub_rows, sub_headers in table_blocks:
        if (merged_blocks and merged_blocks[-1][0] == sub_title
                and merged_blocks[-1][1] == headers_key):
            merged_blocks[-1][2].extend(sub_rows)
            continue
        merged_blocks.append([sub_title, headers_key, list(sub_rows), sub_headers])

    # Density based on total rows and table count
    is_very_dense = total_rows >= 10 or len(merged_blocks) >= 3
    th_pad = '4px 8px' if is_very_dense else '6px 10px'
    td_pad = '3.5px 8px' if is_very_dense else '5px 10px'
    th_font = '10px' if is_very_dense else '11px'
    td_font = '9.5px' if is_very_dense else '10.5px'
    title_margin = '4px 0 2px' if is_very_dense else '8px 0 4px'
    wrap_margin = '4px' if is_very_dense else '6px'

    rendered_tables = []
    for sub_title, headers_key, sub_rows, sub_headers in merged_blocks:
        th_cells = ''.join(f'<th style="background:{primary};color:#fff;padding:{th_pad};font-size:{th_font};text-align:center;vertical-align:middle;">{html_lib.escape(str(h))}</th>' for h in sub_headers)
        tb_rows = []
        for r_idx, r in enumerate(sub_rows):
            vals = list(r.values()) if isinstance(r, dict) else list(r) if isinstance(r, (list, tuple)) else [r]
            td_cells = []
            bg = '#f8fafc' if r_idx % 2 == 1 else '#ffffff'
            for idx, v in enumerate(vals):
                formatted, is_num = _format_table_num(v)
                cls = ' class="numeric"' if is_num and idx > 0 else ''
                direction = 'ltr' if is_num else 'rtl'
                td_cells.append(f'<td{cls} style="padding:{td_pad};font-size:{td_font};text-align:center;vertical-align:middle;direction:{direction};">{formatted}</td>')
            tb_rows.append(f'<tr style="background:{bg};">{"".join(td_cells)}</tr>')

        title_block = f'<div style="font-size:11.5px;font-weight:700;color:{primary};margin:{title_margin};">{html_lib.escape(sub_title)}</div>' if sub_title else ''
        rendered_tables.append(f'''
        <div style="margin-bottom:{wrap_margin};">
          {title_block}
          <div class="financial-table-wrap" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
            <table class="financial-table" data-preserve-density="1">
              <thead><tr>{th_cells}</tr></thead>
              <tbody>{"".join(tb_rows)}</tbody>
            </table>
          </div>
        </div>
        ''')

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""
    if not merged_blocks:
        return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <div style="padding:90px 58px 60px;box-sizing:border-box;">
    <h1 style="font-size:26px;font-weight:800;color:{primary};margin:0 0 14px;">{title}</h1>
    <p style="font-size:15px;line-height:2;color:#475569;margin:0;">لا توجد بيانات معتمدة لعرضها في هذا القسم.</p>
  </div>
  <div data-slide-footer="1" style="position:absolute;bottom:0;right:0;left:0;height:36px;background:{primary};display:flex;align-items:center;justify-content:space-between;padding:0 24px;box-sizing:border-box;">
    <span style="font-size:12px;font-weight:700;color:#ffffff;">{project_title}</span>
    <span data-slide-counter="1" dir="ltr" style="font-size:12px;font-weight:700;color:#ffffff;">{slide_num_str}</span>
  </div>
</div>'''

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">FINANCIAL TABLES</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">جداول وبيانات الخطة المالية التفصيلية المعتمدة للمشروع</p>
      </div>
    </div>
  </header>
  <div class="stacked-financial-tables" style="padding:0 36px;margin-top:68px;display:flex;flex-direction:column;max-height:580px;overflow:hidden;">
    {"".join(rendered_tables)}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">جداول الدراسة المالية المعتمدة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _market_value_html(value):
    return html_lib.escape(html_lib.unescape(str(value or 'غير متوفر'))).replace('\n', '<br>')


def _market_paragraph_blocks(value, count=3):
    """Split approved prose into visual blocks without changing its wording."""
    text = re.sub(r'\s+', ' ', str(value or '').strip())
    if not text:
        return []
    sentences = [item.strip() for item in re.split(r'(?<=[.!؟])\s+', text) if item.strip()]
    if len(sentences) <= 1:
        words = text.split()
        size = max(1, (len(words) + count - 1) // count)
        return [' '.join(words[index:index + size]) for index in range(0, len(words), size)]
    block_size = max(1, (len(sentences) + count - 1) // count)
    return [" ".join(sentences[index:index + block_size]) for index in range(0, len(sentences), block_size)]


def _build_market_scope_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the market scope as an editorial overview instead of a raw key/value table."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    rows = _market_scope_rows(market)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'نطاق الدراسة'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    midpoint = (len(rows) + 1) // 2
    columns = (rows[:midpoint], rows[midpoint:])

    def render_row(label, value):
        return (
            f'<div style="padding:16px 18px;border-bottom:1px solid #e2e8f0;box-sizing:border-box;">'
            f'<div style="font-size:13px;font-weight:800;color:{primary};margin-bottom:6px;">{html_lib.escape(str(label))}</div>'
            f'<div style="font-size:14px;line-height:1.75;color:#334155;text-align:justify;">{_market_value_html(value)}</div></div>'
        )

    column_html = ''.join(
        f'<div style="background:#ffffff;border:1px solid #dbe4ee;border-top:4px solid {primary};border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.03);">'
        + ''.join(render_row(label, value) for label, value in column)
        + '</div>'
        for column in columns if column
    )
    city = str(source.get('city') or '').strip()
    district = str(source.get('district') or '').strip()
    location_line = ' — '.join(item for item in (district, city) if item)
    location_html = (
        f'<div style="background:#f1f5f9;border-radius:10px;padding:12px 18px;border:1px solid #cbd5e1;min-width:200px;">'
        f'<div style="font-size:11px;font-weight:800;color:#475569;margin-bottom:4px;">النطاق الجغرافي للمشروع</div>'
        f'<div style="font-size:16px;font-weight:800;color:{primary};">{html_lib.escape(location_line)}</div></div>'
    ) if location_line else ''

    # Additional contextual highlights so the slide feels rich and comprehensive
    context_cards = []
    prop_type = str(source.get('property_type') or source.get('project_type') or '').strip()
    if prop_type:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">نوع الأصل الاستثماري</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(prop_type)}</div></div>')
    decision = str(market.get('decision') or '').strip()
    if decision:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">تصنيف ملاءمة السوق</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{accent};margin-top:2px;">{html_lib.escape(decision)}</div></div>')
    sources_count = len(market.get('sources') or [])
    if sources_count:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">المصادر المرجعية المعتمدة</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{primary};margin-top:2px;">{sources_count} مصادر بيانات</div></div>')
    highlights_html = (
        f'<div style="margin-top:16px;display:grid;grid-template-columns:repeat({len(context_cards)}, 1fr);gap:14px;">{"".join(context_cards)}</div>'
        if context_cards else ''
    )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SCOPE</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">الإطار الجغرافي والزمني والمنهجي المعتمد لقراءة السوق</p>
      </div>
    </div>
  </header>
  <div data-market-scope="1" style="padding:0 36px;margin-top:14px;">
    <div style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;padding:22px 24px;box-sizing:border-box;">
      <div style="display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid #dbe4ee;padding-bottom:14px;margin-bottom:16px;direction:rtl;">
        <div><div style="font-size:22px;font-weight:800;color:{primary};">تعريف السوق ونطاق الدراسة</div><div style="font-size:12px;color:#64748b;margin-top:5px;">المحددات والمعايير التي تحكم مجال المقارنة والتحليل</div></div>
        {location_html}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start;">
        {column_html}
      </div>
      {highlights_html}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل السوق — نطاق الدراسة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


_MARKET_NUMERAL_RE = re.compile(
    r'\d[\d,]*(?:\.\d+)?(?:\s*(?:%|ر\.س|ريال|مليون|م²|كم|سنة|سنوات|شهرًا?|وحدة|شقة|غرفة|دقيقة))?')


def _market_rich_text(value, accent, weight='700'):
    """Escape approved text and bold the figures already inside it."""
    text = html_lib.escape(html_lib.unescape(str(value or ''))).replace('\n', '<br>')
    return _MARKET_NUMERAL_RE.sub(
        rf'<strong style="color:{accent};font-weight:{weight};">\g<0></strong>', text)


def _build_market_summary_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render one readable page of the detailed market analysis."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    rows, _row_offset = _market_rows_for_slide(
        slide, 'market_study_data.summary', _market_summary_rows(market)
    )
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل السوق'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    is_prose = isinstance(market.get('summary'), str) and bool(str(market.get('summary') or '').strip())
    subtitle = 'قراءة تحليلية للعرض والطلب والمنافسة والفرصة الاستثمارية'
    compact = len(rows) <= 2

    def topic_text_html(value, accent_color, weight='700'):
        return _market_rich_text(value, accent_color, weight)

    if is_prose:
        prose_blocks = _market_paragraph_blocks(rows[0][1] if rows else '', 3)
        prose_rows = ''.join(
            f'<div data-market-analysis-block="{index + 1}" style="display:flex;gap:16px;padding:14px 2px;'
            f'border-bottom:1px solid #e2e8f0;align-items:flex-start;">'
            f'<span style="font-size:22px;font-weight:800;color:{accent};line-height:1.1;min-width:34px;">{index + 1:02d}</span>'
            f'<div style="flex:1;font-size:13.5px;line-height:1.9;color:#1f2937;text-align:justify;">'
            f'{topic_text_html(block, accent)}</div></div>'
            for index, block in enumerate(prose_blocks)
        )
        body_content = (
            f'<div data-market-analysis="1" style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;'
            f'padding:10px 26px;box-sizing:border-box;">{prose_rows}</div>'
        )
    else:
        decision = str(market.get('decision') or '').strip()
        decision_html = (
            f'<div style="display:flex;align-items:center;gap:12px;background:#f8fafc;border:1px solid #e2e8f0;'
            f'border-right:4px solid {accent};border-radius:8px;padding:8px 16px;margin-bottom:12px;">'
            f'<span style="font-size:11px;font-weight:700;color:#64748b;white-space:nowrap;">تصنيف الدراسة</span>'
            f'<span style="font-size:14px;font-weight:800;color:{primary};">{html_lib.escape(decision)}</span></div>'
        ) if decision and _row_offset == 0 else ''

        lead_label, lead_value = rows[0] if rows else ('تحليل السوق', '')
        lead_columns = 'column-count:2;column-gap:34px;' if len(str(lead_value or '')) > 320 else ''
        lead_font = '14.5px' if compact else '13.5px'
        lead_html = (
            f'<div style="background:{primary};border-radius:12px;padding:{26 if compact else 20}px 28px;'
            f'box-sizing:border-box;position:relative;overflow:hidden;">'
            f'<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:{12 if compact else 8}px;">'
            f'<span style="font-size:30px;font-weight:800;color:{accent};line-height:1;">{_row_offset + 1:02d}</span>'
            f'<span style="font-size:{19 if compact else 17}px;font-weight:800;color:#ffffff;">{html_lib.escape(str(lead_label))}</span>'
            f'<span style="flex:1;border-bottom:1px solid rgba(255,255,255,0.22);transform:translateY(-6px);"></span>'
            f'</div>'
            f'<div style="font-size:{lead_font};line-height:1.85;color:#eef2f7;text-align:justify;{lead_columns}">'
            f'{topic_text_html(lead_value, accent)}</div>'
            f'</div>'
        )

        def render_topic(index, label, value):
            text_len = len(re.sub(r'\s+', ' ', str(value or '')).strip())
            columns = 'column-count:2;column-gap:30px;' if text_len > 420 else ''
            body_font = '13px' if compact else '12.5px'
            return (
                f'<div data-market-analysis-topic="{index}" style="padding:{14 if compact else 11}px 2px 0;">'
                f'<div style="display:flex;align-items:baseline;gap:12px;">'
                f'<span style="font-size:{24 if compact else 21}px;font-weight:800;color:{accent};line-height:1;min-width:34px;">{index:02d}</span>'
                f'<span style="font-size:{15.5 if compact else 14}px;font-weight:800;color:{primary};white-space:nowrap;">{html_lib.escape(str(label))}</span>'
                f'<span style="flex:1;border-bottom:1px solid #e2e8f0;transform:translateY(-5px);"></span>'
                f'</div>'
                f'<div style="margin-top:{8 if compact else 5}px;font-size:{body_font};line-height:{1.85 if compact else 1.72};'
                f'color:#334155;text-align:justify;{columns}">{topic_text_html(value, accent)}</div>'
                f'</div>'
            )

        topics_html = ''.join(
            render_topic(_row_offset + idx + 1, label, value)
            for idx, (label, value) in enumerate(rows[1:], 1)
        )
        body_content = (
            f'<div data-market-analysis="1" style="display:flex;flex-direction:column;">'
            f'{decision_html}{lead_html}{topics_html}</div>'
        )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SUMMARY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">{subtitle}</p>
      </div>
    </div>
  </header>
  <div style="padding:0 40px;margin-top:12px;">
    {body_content}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل السوق</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _market_one_block_paragraph(market):
    """Return the executive market summary as one prose paragraph."""
    value = str((market or {}).get('one_block_summary') or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    try:
        import market_study
        is_paragraph = market_study.is_market_summary_paragraph(value)
    except Exception:
        is_paragraph = bool(value and not re.search(r'(?m)^\s*\d+[.)]\s+', value))
    if is_paragraph:
        return re.sub(r'\s+', ' ', value).strip()
    summary = (market or {}).get('summary')
    if isinstance(summary, dict):
        try:
            import market_study
            fallback = market_study.summary_prose(summary)
        except Exception:
            fallback = ' '.join(str(summary.get(key) or '').strip() for key in (
                'market_definition', 'city_position', 'sector_performance', 'supply',
                'demand', 'competition', 'market_gap', 'recommendation', 'risks'
            ) if str(summary.get(key) or '').strip())
        if fallback:
            return re.sub(r'\s+', ' ', fallback).strip()
    return re.sub(r'\s+', ' ', str(summary or '').strip()).strip() if isinstance(summary, str) else re.sub(r'\s+', ' ', value).strip()


def _market_one_block_text(slide, market):
    source = str((slide or {}).get('content_source') or '')
    value = _market_one_block_paragraph(market)
    match = re.fullmatch(r'market_study_data\.one_block_summary:(\d+):(\d+)', source)
    if match:
        value = value[int(match.group(1)):int(match.group(2))]
    return value.strip()


def _build_market_one_block_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the complete work-market summary as one full-width paragraph."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    value = _market_one_block_text(slide, market)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'ملخص دراسة سوق العمل'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    market = _market_state(source)
    blocks = _market_paragraph_blocks(value, 3)
    decision = str(market.get('decision') or '').strip()
    disclaimer = str(market.get('disclaimer') or '').strip()
    block_html = ''.join(
        f'<p style="padding:0 0 17px;margin:0 0 17px;'
        f'border-bottom:1px solid #dbe4ee;font-size:13.4px;line-height:1.9;color:#1f2937;text-align:justify;" data-market-work-block="{index + 1}">'
        f'{_market_value_html(block)}</p>'
        for index, block in enumerate(blocks)
    )
    aside_parts = []
    if decision:
        aside_parts.append(
            f'<div style="background:{primary};color:#ffffff;border-radius:10px;padding:18px 16px;margin-bottom:16px;">'
            f'<div style="font-size:12px;font-weight:800;margin-bottom:8px;">تصنيف الدراسة</div>'
            f'<div style="font-size:18px;font-weight:800;line-height:1.45;">{html_lib.escape(decision)}</div></div>'
        )
    aside_parts.append(
        f'<div style="border-right:5px solid {accent};padding:7px 16px 7px 6px;">'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:9px;">خلاصة القرار</div>'
        f'<div style="font-size:12px;line-height:1.85;color:#475569;text-align:justify;">قراءة السوق تجمع المؤشرات المعتمدة في مسار واحد لاتخاذ القرار.</div></div>'
    )
    if disclaimer:
        aside_parts.append(
            f'<div style="background:#e8dcc0;border-radius:10px;padding:14px 16px;margin-top:20px;color:#1f2937;">'
            f'<div style="font-size:12px;font-weight:800;margin-bottom:7px;">إخلاء المسؤولية</div>'
            f'<div style="font-size:11.5px;line-height:1.7;text-align:justify;">{_market_value_html(disclaimer)}</div></div>'
        )
    # This is only the emergency renderer used when SOL is unavailable. Keep
    # it in ordinary block flow so browser and PDF engines cannot overlap the
    # decision card with the narrative when CSS grid support differs.
    body_html = (
        f'<div data-market-work-summary="1" style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;'
        f'padding:20px 26px;min-height:0;max-height:none;overflow:visible;box-sizing:border-box;box-shadow:0 3px 10px rgba(15,23,42,.05);'
        f'display:block;direction:rtl;">'
        f'<div style="border-right:5px solid {accent};padding:0 16px 12px 6px;margin-bottom:16px;">'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:9px;">ملخص القرار</div>'
        f'<div style="font-size:12px;line-height:1.85;color:#475569;text-align:justify;">قراءة السوق تجمع المؤشرات المعتمدة في مسار واحد لاتخاذ القرار.</div></div>'
        f'<div style="display:block;">'
        f'<div style="font-size:22px;font-weight:800;color:{primary};margin:0 0 14px;text-align:right;">القراءة النهائية للسوق</div>'
        f'{block_html}</div>'
        f'{("".join(aside_parts[:1])) if decision else ""}'
        f'{("".join(aside_parts[-1:])) if disclaimer else ""}'
        f'</div>'
    )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET WORK SUMMARY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">النص الكامل المعتمد لدراسة سوق العمل</p>
      </div>
    </div>
  </header>
  <div style="padding:0 42px;margin-top:12px;overflow:visible;">
    {body_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">ملخص دراسة سوق العمل</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_sources_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render one readable page of the source register as two table columns."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    page_rows, row_offset = _market_rows_for_slide(
        slide, 'market_study_data.sources', _market_source_rows(market)
    )
    columns = _market_source_chunks(market, page_rows)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مصادر دراسة السوق'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    def field(value, direction='rtl', size='9px'):
        return f'<div dir="{direction}" style="font-size:{size};line-height:1.2;word-break:break-word;overflow-wrap:anywhere;">{_market_value_html(value)}</div>'

    def render_column(column_rows, column_index):
        header = (
            '<div style="display:grid;grid-template-columns:1.12fr 1.55fr 1.18fr 1.25fr;'
            f'gap:0;background:{primary};color:#fff;font-size:9px;font-weight:800;text-align:center;line-height:1.2;">'
            '<div style="padding:7px 5px;">المصدر</div><div style="padding:7px 5px;">الرابط</div>'
            '<div style="padding:7px 5px;">التواريخ والموثوقية</div><div style="padding:7px 5px;">الملاحظات</div></div>'
        )
        start_number = row_offset + 1 + sum(len(item) for item in columns[:column_index])
        end_number = start_number + len(column_rows) - 1
        range_title = f'مصادر {start_number} - {end_number}' if column_rows else 'مصادر'
        rows_html = []
        for row_index, row in enumerate(column_rows):
            name, url, data_date, accessed, reliability, note = list(row) + [''] * max(0, 6 - len(row))
            meta_parts = []
            if str(data_date or '').strip():
                meta_parts.append('تاريخ البيانات: ' + str(data_date).strip())
            if str(accessed or '').strip():
                meta_parts.append('تاريخ الوصول: ' + str(accessed).strip())
            if str(reliability or '').strip():
                meta_parts.append('الموثوقية: ' + str(reliability).strip())
            meta = '<br>'.join(html_lib.escape(part) for part in meta_parts) or 'غير متوفر'
            bg = '#f8fafc' if row_index % 2 else '#ffffff'
            rows_html.append(
                f'<div style="display:grid;grid-template-columns:1.12fr 1.55fr 1.18fr 1.25fr;gap:0;'
                f'background:{bg};border-bottom:1px solid #e2e8f0;align-items:center;">'
                f'<div style="padding:8px 6px;text-align:center;font-size:9.3px;line-height:1.35;word-break:break-word;">{_market_value_html(name)}</div>'
                f'<div style="padding:8px 6px;text-align:center;">{field(url, "ltr", "8px")}</div>'
                f'<div style="padding:8px 6px;text-align:center;font-size:8.4px;line-height:1.35;word-break:break-word;">{meta}</div>'
                f'<div style="padding:8px 6px;text-align:center;">{field(note, "rtl", "8.7px")}</div>'
                '</div>'
            )
        return (
            f'<div style="border:1px solid #dbe4ee;border-radius:8px;overflow:hidden;min-width:0;box-shadow:0 2px 7px rgba(15,23,42,.04);">'
            f'<div style="padding:8px 10px;background:#f8fafc;color:{primary};font-size:10.5px;font-weight:800;">{range_title}</div>'
            f'{header}{"".join(rows_html)}</div>'
        )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SOURCES</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">السجل الكامل للمراجع والروابط الرسمية المستخدمة في الدراسة</p>
      </div>
    </div>
  </header>
  <div data-market-sources="1" style="margin:12px 36px 0;padding:14px 16px 18px;background:#f3f6f8;border:1px solid #dbe4ee;border-top:5px solid {primary};border-radius:12px;box-sizing:border-box;">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:12px;direction:rtl;">
      <div style="font-size:16px;font-weight:800;color:{primary};">سجل المراجع المستخدمة في الدراسة</div>
      <div style="font-size:10.5px;color:#64748b;">روابط وبيانات المصادر كما وردت</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start;">
      {''.join(render_column(column, index) for index, column in enumerate(columns))}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">المراجع والمصادر الرسمية لدراسة السوق</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_swot_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render SWOT as a readable four-quadrant matrix instead of raw JSON."""
    source = source if isinstance(source, dict) else {}
    swot = _extract_project_swot(source)
    definitions = (
        ('strengths', 'نقاط القوة', '#0f766e', '#ecfdf5'),
        ('weaknesses', 'نقاط الضعف', '#b45309', '#fffbeb'),
        ('opportunities', 'الفرص', '#1d4ed8', '#eff6ff'),
        ('threats', 'التهديدات', '#b91c1c', '#fef2f2'),
    )
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل SWOT'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    quadrants = []
    for key, label, color, background in definitions:
        items = _market_swot_items(swot.get(key))
        item_html = ''.join(
            f'<div style="padding:6px 0;border-bottom:1px solid rgba(15,23,42,0.08);font-size:12.2px;line-height:1.42;color:#334155;">{_market_value_html(item)}</div>'
            for item in items
        ) or '<div style="font-size:12px;color:#64748b;">غير متوفر</div>'
        quadrants.append(
            f'<div style="background:{background};border:1px solid rgba(15,23,42,0.10);border-top:5px solid {color};'
            'border-radius:8px;padding:12px 16px;box-sizing:border-box;min-width:0;overflow:visible;">'
            f'<div style="font-size:16px;font-weight:800;color:{color};margin-bottom:5px;">{label}</div>'
            f'{item_html}</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">SWOT ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مصفوفة نقاط القوة والضعف والفرص والتهديدات للمشروع في السوق المحدد</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;height:526px;align-items:stretch;">
      {''.join(quadrants)}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل SWOT للمشروع</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_risk_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render approved risks as a clear risk-to-mitigation register."""
    source = source if isinstance(source, dict) else {}
    _risk_source, items = _risk_analysis_source(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل المخاطر وطرق المعالجة'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    dense = len(items) >= 7
    cell_padding = '8px 12px' if dense else '12px 14px'
    body_size = '10.8px' if dense else '12px'
    row_html = []
    for index, item in enumerate(items, 1):
        risk = _market_value_html(item.get('risk'))
        mitigation = _market_value_html(item.get('mitigation')) if item.get('mitigation') else 'غير محددة في البيانات المعتمدة'
        background = '#ffffff' if index % 2 else '#f8fafc'
        row_html.append(
            f'<div data-risk-row="{index}" style="display:grid;grid-template-columns:1fr 1.35fr;gap:0;'
            f'background:{background};border-bottom:1px solid #dbe4ee;align-items:stretch;">'
            f'<div style="padding:{cell_padding};border-right:3px solid #d7a4a4;color:#27364a;font-size:{body_size};line-height:1.5;">'
            f'<div style="font-size:10px;font-weight:800;color:#b45309;margin-bottom:4px;" dir="ltr">{index:02d}</div>{risk}</div>'
            f'<div style="padding:{cell_padding};border-right:1px solid #e2e8f0;color:#334155;font-size:{body_size};line-height:1.5;">{mitigation}</div>'
            '</div>'
        )
    if not row_html:
        row_html.append(
            '<div style="padding:18px;font-size:12px;color:#64748b;">لا توجد بيانات مخاطر معتمدة لعرضها.</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">RISK ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">سجل المخاطر المرتبطة بالمشروع وطرق معالجتها من البيانات المعتمدة</p>
      </div>
    </div>
  </header>
  <div data-risk-register="1" style="padding:0 42px;margin-top:16px;">
    <div style="border-top:4px solid {primary};border-bottom:1px solid #dbe4ee;overflow:hidden;">
      <div style="display:grid;grid-template-columns:1fr 1.35fr;background:{primary};color:#ffffff;font-size:12px;font-weight:800;line-height:1.25;">
        <div style="padding:10px 14px;border-right:1px solid rgba(255,255,255,.35);">المخاطر</div>
        <div style="padding:10px 14px;">طريقة المعالجة</div>
      </div>
      {''.join(row_html)}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل المخاطر وطرق المعالجة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _visual_media_content_source(slide):
    item = slide if isinstance(slide, dict) else {}
    return str(item.get('content_source') or item.get('contentSource') or '').strip().lower()


def _visual_media_image_tokens(slide):
    item = slide if isinstance(slide, dict) else {}
    values = item.get('image_tokens')
    if not isinstance(values, list):
        values = item.get('imageTokens')
    return [str(token or '').strip() for token in (values or []) if str(token or '').strip()]


def _visual_media_tokens_from_source(slide):
    source = _visual_media_content_source(slide)
    match = re.fullmatch(r'plan_image:(\d+)', source)
    if match and int(match.group(1)) > 0:
        return [f'##PLAN_IMAGE_{int(match.group(1))}##']
    match = re.fullmatch(r'exterior_image:(\d+)', source)
    if match and int(match.group(1)) > 0:
        return [f'##MOODBOARD_IMAGE_{int(match.group(1))}##']
    match = re.fullmatch(r'exterior_images_group:(\d+):(\d+)', source)
    if match:
        start, end = sorted((int(match.group(1)), int(match.group(2))))
        if start > 0:
            return [f'##MOODBOARD_IMAGE_{index}##' for index in range(start, min(end, start + 29) + 1)]
    match = re.fullmatch(r'interior_image:(\d+):(\d+)', source)
    if match and int(match.group(1)) > 0 and int(match.group(2)) > 0:
        return [f'##INTERIOR_COMP_{int(match.group(1))}_IMG_{int(match.group(2))}##']
    match = re.fullmatch(r'interior_images_group:(\d+):(\d+):(\d+)', source)
    if match:
        component = int(match.group(1))
        start, end = sorted((int(match.group(2)), int(match.group(3))))
        if component > 0 and start > 0:
            return [
                f'##INTERIOR_COMP_{component}_IMG_{index}##'
                for index in range(start, min(end, start + 29) + 1)
            ]
    return []


def _usable_legacy_visual_media_url(value, attrs_text=''):
    url = html_lib.unescape(str(value or '').strip()).strip('"\' ')
    if not url or '##' in url or url.lower().startswith(('blob:', 'javascript:', 'about:')):
        return ''
    if re.search(r'(?:logo|شعار|data-cover|cover-overlay)', attrs_text, flags=re.IGNORECASE):
        return ''
    if re.search(
        r'(?:tenant-assets|/api/branding/|(?:^|[/_.-])(?:project[-_])?logo(?:[/_.?&-]|$))',
        url, flags=re.IGNORECASE,
    ):
        return ''
    if re.search(
        r'(?:^|/)uploads/maps(?:/|$)|(?:^|/)api/map-images(?:/|$)|(?:^|/)map_[^/]*(?:\?|$)',
        url, flags=re.IGNORECASE,
    ):
        return ''
    if not (
        url.startswith(('/', 'http://', 'https://', 'data:image/'))
        or re.search(r'\.(?:avif|bmp|gif|jpe?g|png|webp)(?:\?.*)?$', url, flags=re.IGNORECASE)
    ):
        return ''
    return url


class _LegacyVisualMediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def _append(self, value, attrs_text):
        url = _usable_legacy_visual_media_url(value, attrs_text)
        if url and url not in self.urls:
            self.urls.append(url)

    def handle_starttag(self, tag, attrs):
        values = {str(key or '').lower(): str(value or '') for key, value in attrs}
        attrs_text = ' '.join(
            f'{key}={value}' for key, value in values.items() if key not in {'src', 'style'}
        )
        if str(tag or '').lower() == 'img':
            self._append(values.get('src'), attrs_text)
        style = values.get('style') or ''
        for match in re.finditer(r'url\(\s*(["\']?)(.*?)\1\s*\)', style, flags=re.IGNORECASE):
            self._append(match.group(2), attrs_text)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _legacy_visual_media_urls(slide):
    html = _strip_existing_slide_chrome(str((slide or {}).get('html') or ''))
    if not html:
        return []
    parser = _LegacyVisualMediaParser()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return []
    return parser.urls[:30]


def _legacy_visual_media_layout_marked(slide):
    item = slide if isinstance(slide, dict) else {}
    html = str(item.get('html') or '')
    if not _legacy_visual_media_urls(item):
        return False
    if item.get('media_only') or str(item.get('design_style') or item.get('designStyle') or '').strip().lower() == 'image':
        return True
    return bool(re.search(
        r'data-(?:visual-media-only|visual-media-grid|legacy-media-frame)',
        html, flags=re.IGNORECASE,
    ))


def _is_visual_concept_media_slide(slide):
    source = _visual_media_content_source(slide)
    section = _slide_section_key(slide or {})
    token_names = [token.strip('#').upper() for token in _visual_media_image_tokens(slide)]
    has_visual_token = any(token.startswith((
        'PLAN_IMAGE_', '2D_PLAN_', 'MOODBOARD_IMAGE_', 'PROJECT_IMAGE_',
        'INTERIOR_COMP_', 'INTERIOR_C', 'INTERIOR_IMAGE_', 'INTERIOR_',
    )) for token in token_names)
    has_visual_source = source.startswith((
        'plan_image:', 'exterior_image:', 'exterior_images_group:',
        'interior_image:', 'interior_images_group:',
    ))
    return section in {'plans', 'exterior', 'interior'} and (
        has_visual_token or has_visual_source or _legacy_visual_media_layout_marked(slide)
    )


def _creative_asset_url(value):
    source = value if isinstance(value, dict) else {'url': value}
    url = str(
        source.get('approvedImageUrl') or source.get('approved_image_url')
        or source.get('imageUrl') or source.get('image_url')
        or source.get('url') or source.get('path') or ''
    ).strip()
    if url.lower() in {'', 'available', 'blob:', 'undefined', 'null', 'none'} or url.lower().startswith('blob:'):
        return ''
    return url


def _visual_media_token_url(token, creative_images):
    images = creative_images if isinstance(creative_images, dict) else {}
    name = str(token or '').strip().strip('#').upper()

    match = re.fullmatch(r'(?:MOODBOARD_IMAGE|PROJECT_IMAGE)_(\d+)', name)
    if match:
        values = images.get('moodboard') or images.get('moodboardImages') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''

    match = re.fullmatch(r'(?:PLAN_IMAGE|2D_PLAN)_(\d+)', name)
    if match:
        values = images.get('plans') or images.get('plans2d') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''

    match = re.fullmatch(r'INTERIOR_(?:COMP_)?(\d+)_(?:IMG|IMAGE)_(\d+)', name)
    if not match:
        match = re.fullmatch(r'INTERIOR_C(\d+)_(?:IMG|IMAGE)_(\d+)', name)
    if not match:
        match = re.fullmatch(r'INTERIOR_(\d+)_(\d+)', name)
    if match:
        components = images.get('interior_components') or []
        component_index = int(match.group(1)) - 1
        image_index = int(match.group(2)) - 1
        if isinstance(components, list) and 0 <= component_index < len(components):
            component = components[component_index]
            values = component.get('images') if isinstance(component, dict) else []
            if isinstance(values, list) and 0 <= image_index < len(values):
                return _creative_asset_url(values[image_index])
        return ''

    match = re.fullmatch(r'INTERIOR_(?:IMAGE_)?(\d+)', name)
    if match:
        values = images.get('interior') or images.get('interior_images') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''
    return ''


def _visual_media_rebuild_sources(slide, creative_images):
    inferred_tokens = _visual_media_tokens_from_source(slide)
    if inferred_tokens and all(_visual_media_token_url(token, creative_images) for token in inferred_tokens):
        return inferred_tokens, inferred_tokens

    tokens = _visual_media_image_tokens(slide)
    if tokens and all(_visual_media_token_url(token, creative_images) for token in tokens):
        return tokens, tokens

    direct_sources = [
        _usable_legacy_visual_media_url(token)
        for token in tokens
    ]
    if tokens and all(direct_sources):
        return direct_sources, []

    return _legacy_visual_media_urls(slide), []


def _extract_visual_concept_captions(html):
    """Extract existing captions or description texts from visual slide HTML."""
    if not html or not isinstance(html, str):
        return []
    explicit = re.findall(
        r'<div[^>]*data-visual-media-caption="1"[^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if explicit:
        results = [re.sub(r'<[^>]+>', '', cap).strip() for cap in explicit]
        results = [cap for cap in results if cap]
        if results:
            return results
    generic = re.findall(
        r'<(?:div|p|span)[^>]*(?:class|data-role)=["\'][^"\']*(?:caption|description|desc)[^"\']*["\'][^>]*>(.*?)</(?:div|p|span)>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if generic:
        results = [re.sub(r'<[^>]+>', '', cap).strip() for cap in generic]
        results = [cap for cap in results if cap]
        if results:
            return results
    return []


def _build_visual_concept_media_slide(slide, branding=None):
    """Build a media visual-concept slide with prominent component/title header and captions."""
    tokens = [str(token).strip() for token in ((slide or {}).get('image_tokens') or []) if str(token).strip()]
    if not tokens:
        return None
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    title = html_lib.escape(str((slide or {}).get('title') or '').strip())
    component_name = html_lib.escape(str((slide or {}).get('component_name') or '').strip())

    captions = (slide or {}).get('captions')
    if not isinstance(captions, list) or not any(str(c or '').strip() for c in captions):
        captions = (slide or {}).get('bullets')
    if not isinstance(captions, list) or not any(str(c or '').strip() for c in captions):
        extracted = _extract_visual_concept_captions((slide or {}).get('html'))
        if extracted:
            captions = extracted
            if isinstance(slide, dict):
                slide['captions'] = list(extracted)
    if not isinstance(captions, list):
        captions = []
    description = str((slide or {}).get('description') or '').strip()
    if not description and captions:
        description = str(captions[0] or '').strip()

    columns = 1 if len(tokens) == 1 else 2

    header_html = ''
    if title or component_name:
        badge = f'<span style="font-size:14px;font-weight:700;color:{secondary};background:#f0f9ff;padding:4px 12px;border-radius:6px;border:1px solid #bae6fd;">{component_name}</span>' if (component_name and component_name not in title) else ''
        header_html = (
            f'<div data-visual-media-title="1" style="position:absolute;top:72px;right:34px;left:34px;height:40px;'
            f'display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;'
            f'border-bottom:2px solid #eef2f6;box-sizing:border-box;">'
            f'<div style="font-size:24px;font-weight:800;color:{primary};letter-spacing:-0.3px;">{title}</div>'
            f'{badge}'
            f'</div>'
        )

    cards = []
    for i, token in enumerate(tokens):
        cap = ''
        if i < len(captions) and str(captions[i] or '').strip():
            cap = str(captions[i]).strip()
        elif description:
            cap = description

        cap_html = ''
        if cap:
            escaped_cap = html_lib.escape(cap)
            cap_html = (
                f'<div data-visual-media-caption="1" style="margin-top:10px;padding:10px 14px;background:#f8fafc;'
                f'border:1px solid #e2e8f0;border-radius:8px;font-size:14px;font-weight:600;color:#334155;'
                f'line-height:1.5;text-align:center;box-sizing:border-box;width:100%;">'
                f'{escaped_cap}</div>'
            )

        card = (
            '<div style="min-width:0;min-height:0;display:flex;flex-direction:column;'
            'overflow:hidden;height:100%;box-sizing:border-box;">'
            '<div data-visual-media-frame="1" style="position:relative;flex:1;min-height:0;overflow:hidden;'
            'border:1px solid #d9e1ea;border-radius:12px;background:#fff;box-sizing:border-box;">'
            f'<img data-visual-media-image="1" src="{html_lib.escape(token, quote=True)}" alt="" '
            'style="position:absolute!important;inset:0!important;display:block!important;'
            'width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important;'
            'object-fit:contain!important;object-position:center center!important;">'
            '</div>'
            f'{cap_html}'
            '</div>'
        )
        cards.append(card)

    images_grid = ''.join(cards)
    grid_top = 126 if header_html else 72

    return (
        '<div class="slide" dir="rtl" data-visual-media-only="1" '
        'style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;'
        'padding:72px 34px 48px;box-sizing:border-box;">'
        f'{header_html}'
        f'<div data-visual-media-grid="1" style="position:absolute;top:{grid_top}px;right:34px;bottom:48px;left:34px;'
        f'display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));'
        'gap:16px;min-width:0;min-height:0;overflow:hidden;align-items:stretch;">'
        f'{images_grid}</div></div>'
    )
