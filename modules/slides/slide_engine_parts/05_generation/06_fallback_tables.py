

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
            rows = [[it.get('name', ''), f"{format_financial_number(it.get('value_sar', 0))} ر.س" if it.get('value_sar') else it.get('display', '')] for it in items]
            if w_data.get('total'):
                rows.append([w_data['total'].get('name', 'الإجمالي'), f"{format_financial_number(w_data['total'].get('value_sar', 0))} ر.س" if w_data['total'].get('value_sar') else w_data['total'].get('display', '')])
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
        # as the PDF note) instead of an empty table. The values are the
        # approved display strings — a raw projection decimal («0.2345») would
        # contradict the number the client approved on screen.
        indicator_rows = _financial_indicator_display_rows(model, project_data, limit=12)
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
        en = resolve_offer_lang(project_data) == OFFER_LANG_ENGLISH
        rows = _market_scope_rows(market, 'en' if en else 'ar')
        return (['Item', 'Value'] if en else ['البند', 'القيمة']), rows
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
            en = resolve_offer_lang(project_data) == OFFER_LANG_ENGLISH
            headers = ['Competitor / Project', 'Price', 'Type'] if en else ['المنافس / المشروع', 'السعر', 'النوع']
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
        res = format_financial_number(clean, grouped=True)
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
