# Competitor tables and chart summary helpers.

def _competitor_table_cell(value, fallback='—'):
    text = _competitor_display_text(value, fallback=fallback)
    formatted, is_num = _format_table_num(text)
    return formatted if is_num else html_lib.escape(text)


def _competitor_area_display(comp, offer_lang='ar'):
    area_cache = comp.get('area_cache') if isinstance(comp, dict) and isinstance(comp.get('area_cache'), dict) else {}
    area_fixed = _competitor_value(comp, 'area_sqm', 'area', 'المساحة') or area_cache.get('area_sqm')
    area_from = _competitor_value(comp, 'area_from', 'min_area', 'من') or area_cache.get('area_from')
    area_to = _competitor_value(comp, 'area_to', 'max_area', 'إلى') or area_cache.get('area_to')
    area_mode = str(_competitor_value(comp, 'area_mode', 'mode') or '').strip().lower()
    if area_mode == 'range' or area_from not in (None, '', []) or area_to not in (None, '', []):
        if offer_lang == 'en':
            return f'{_competitor_table_cell(area_from)} – {_competitor_table_cell(area_to)}'
        return f'من {_competitor_table_cell(area_from)} إلى {_competitor_table_cell(area_to)}'
    return _competitor_table_cell(area_fixed)


def _competitor_source_display(comp, offer_lang='ar'):
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
                f'style="color:#2563eb;font-size:9px;">{"Source " if offer_lang == "en" else "المصدر "}{index}</a>'
            )
    if not links:
        return '<div style="color:#94a3b8;">—</div>'
    return '<div style="display:flex;flex-direction:column;gap:3px;align-items:center;">' + ''.join(links) + '</div>'


def _render_competitor_table(competitors, primary, offer_lang='ar'):
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
            no_logo = '—' if offer_lang == 'en' else 'لا يوجد'
            logo_html = f'<div style="height:{logo_height};display:flex;align-items:center;justify-content:center;color:#64748b;">{no_logo}</div>'
        project_type = _competitor_value(comp, 'project_type', 'projectType', 'النوع')
        classification = _competitor_value(comp, 'classification', 'التصنيف')
        type_html = f'<div>{html_lib.escape(_competitor_display_text(project_type))}</div>'
        if classification:
            type_html += f'<div style="margin-top:2px;color:#64748b;font-size:8px;">{html_lib.escape(_competitor_display_text(classification))}</div>'
        operation = _competitor_value(comp, 'operation_type', 'operation', 'نوع العملية')
        status = _competitor_value(comp, 'status', 'الحالة')
        price = html_lib.escape(_competitor_price_display(comp, offer_lang))
        cells = (
            logo_html,
            html_lib.escape(name),
            type_html,
            _competitor_area_display(comp, offer_lang),
            _competitor_table_cell(status),
            _competitor_table_cell(operation),
            price,
            _competitor_source_display(comp, offer_lang),
        )
        bg = '#f8fafc' if len(rows_html) % 2 else '#ffffff'
        cell_dir = 'ltr' if offer_lang == 'en' else 'rtl'
        rows_html.append(
            f'<tr style="background:{bg};">' + ''.join(
                f'<td style="border-bottom:1px solid #e2e8f0;padding:{cell_pad};font-size:{"8.5px" if col_idx in (0, 7) else "9px"};'
                f'text-align:center;direction:{cell_dir};vertical-align:middle;line-height:1.25;word-break:break-word;">{value}</td>'
                for col_idx, value in enumerate(cells)
            ) + '</tr>'
        )
    if not rows_html:
        empty_text = 'No competitor data' if offer_lang == 'en' else 'لا توجد بيانات منافسين'
        return f'<div data-competitor-table="1" style="padding:20px;text-align:center;color:#64748b;border:1px solid #e2e8f0;border-radius:6px;">{empty_text}</div>'
    headers = (('Logo', 'Project', 'Type / Class', 'Area m²', 'Status', 'Operation', 'Pricing', 'Sources')
               if offer_lang == 'en'
               else ('الشعار', 'اسم المشروع', 'النوع والتصنيف', 'المساحة م²', 'الحالة', 'نوع العملية', 'بيانات السعر', 'المصادر'))
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


def _render_fallback_horizontal_bar(items, primary='#005f78', secondary='#0ea5e9', offer_lang='ar'):
    en = offer_lang == 'en'
    if not items:
        empty = 'Not enough competitor data' if en else 'لا تتوفر بيانات منافسين كافية'
        return f'<div style="padding:20px;text-align:center;color:#64748b;">{empty}</div>'
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
        badge = (f'<span style="background:{primary};color:#fff;font-size:10px;padding:2px 6px;border-radius:3px;margin-right:6px;">'
                 f'{"Our Project" if en else "مشروعنا"}</span>') if is_project else ''
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
        f'<div style="font-size:13px;font-weight:700;color:{primary};border-bottom:1px solid #cbd5e1;padding-bottom:6px;">'
        f'{"Market Price Comparison" if en else "مقارنة أسعار المنافسين في السوق"}</div>'
        f'{"".join(rows_html)}'
        f'</div>'
    )


def _market_scope_display(market, offer_lang='ar'):
    if not isinstance(market, dict):
        return ''
    en = offer_lang == 'en'
    radius = market.get('competitor_radius')
    if radius == 'city':
        radius_text = 'Entire City' if en else 'كامل المدينة'
    elif radius == 'custom':
        radius_text = _competitor_display_text(market.get('competitor_radius_custom_km')) + (' km' if en else ' كم')
    elif radius not in (None, ''):
        radius_text = _competitor_display_text(radius) + (' km' if en else ' كم')
    else:
        radius_text = ''
    period_map = (
        {'12m': 'Last 12 months', '24m': 'Last 24 months', '3y': 'Last 3 years', '5y': 'Last 5 years'}
        if en else
        {'12m': 'آخر 12 شهرًا', '24m': 'آخر 24 شهرًا', '3y': 'آخر 3 سنوات', '5y': 'آخر 5 سنوات'}
    )
    period = market.get('data_period')
    period_text = period_map.get(str(period), '') if period not in (None, '') else ''
    if period == 'custom':
        period_text = (f'{_competitor_display_text(market.get("data_period_from"))} – {_competitor_display_text(market.get("data_period_to"))}'
                       if en else
                       f'من {_competitor_display_text(market.get("data_period_from"))} إلى {_competitor_display_text(market.get("data_period_to"))}')
    parts = []
    if radius_text:
        parts.append(f'{"Competitor scope" if en else "نطاق المنافسين"}: {radius_text}')
    if period_text:
        parts.append(f'{"Data period" if en else "فترة البيانات"}: {period_text}')
    return ' | '.join(parts)


def _market_chart_provenance(competitors, offer_lang='ar'):
    en = offer_lang == 'en'
    items = []
    for comp in competitors or []:
        if not isinstance(comp, dict):
            continue
        source = _competitor_display_text(_competitor_value(comp, 'source', 'المصدر'), '')
        data_date = _competitor_display_text(_competitor_value(comp, 'data_date', 'dataDate', 'source_date', 'date', 'تاريخ البيانات'), '')
        if source or data_date:
            text = source or ('Documented source' if en else 'مصدر موثق')
            if data_date:
                text += f'{", data date: " if en else "، تاريخ البيانات: "}{data_date}'
            if text not in items:
                items.append(text)
    if not items:
        return ''
    return ('Comparison sources & dates: ' if en else 'مصدر ووقت بيانات المقارنة: ') + ('; ' if en else '؛ ').join(items)
