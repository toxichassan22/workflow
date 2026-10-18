# Financial chart and slide fallbacks.

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
    total_cost_display = total.get('display', f"{format_precise_number(total_cost_m)} ر.س")
    sorted_items = sorted(items, key=lambda x: x.get('value_millions', 0), reverse=True)
    top2_pct = sum(it.get('pct_of_total', 0) for it in sorted_items[:2]) if sorted_items else 0
    top1_name = sorted_items[0].get('name', 'المكون الرئيسي') if sorted_items else 'المكون الرئيسي'
    top1_val = sorted_items[0].get('display', '—') if sorted_items else '—'

    waterfall_rows = [
        [it.get('name', ''), f"{format_precise_number(it.get('value_sar', 0))} ر.س" if it.get('value_sar') else it.get('display', ''), f"{format_precise_number(it.get('pct_of_total', 0), grouped=False)}%"]
        for it in items
    ]
    if total:
        tot_val_sar = total.get('value_sar', 0)
        tot_val_display = f"{format_precise_number(tot_val_sar)} ر.س" if tot_val_sar else total.get('display', '')
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
        <div class="kpi-val">{format_precise_number(top2_pct, grouped=False)}%</div>
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
        total_inflow = f"{format_precise_number(tot_inf)} مليون ر.س"
    if peak_outflow == '—' and items:
        min_cum = min((it.get('cumulative_m', 0) for it in items), default=0)
        peak_outflow = f"{format_precise_number(abs(min_cum))} مليون ر.س"
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
        f_str = f"({format_precise_number(abs(f_val))})" if f_val < 0 else format_precise_number(f_val)
        c_str = f"({format_precise_number(abs(c_val))})" if c_val < 0 else format_precise_number(c_val)
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
    offer_lang = resolve_offer_lang(source)
    en = offer_lang == OFFER_LANG_ENGLISH
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title')
                                or ('Competitor Price Comparison' if en else 'مقارنة أسعار المنافسين')))
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

    bar_chart_html = _render_fallback_horizontal_bar(items, primary, accent, offer_lang)
    table_html = _render_competitor_table(competitors, primary, offer_lang)
    scope_text = _market_scope_display(market, offer_lang)
    text_align = 'left' if en else 'right'
    scope_html = (
        f'<div style="margin-bottom:10px;color:#64748b;font-size:10px;text-align:{text_align};">'
        f'{html_lib.escape(scope_text)}</div>'
    ) if scope_text else ''
    provenance_text = _market_chart_provenance(competitors, offer_lang)
    provenance_html = (
        f'<div style="margin-top:8px;color:#64748b;font-size:9px;text-align:{text_align};line-height:1.35;">'
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
        lo_text, hi_text = format_precise_number(lo), format_precise_number(hi)
        range_text = (f'{lo_text} – {hi_text}' if en else f'من {lo_text} إلى {hi_text}') if hi > lo else lo_text
        shown_text = f'{len(competitors)} competitors shown' if en else f'{len(competitors)} منافسًا معروضًا'
        range_label = 'Range' if en else 'نطاق'
        stats_html = (
            f'<div style="margin-top:auto;padding-top:10px;display:flex;align-items:center;gap:16px;'
            f'font-size:10.5px;color:#475569;border-top:1px solid #e2e8f0;">'
            f'<span style="font-weight:800;color:{primary};">{shown_text}</span>'
            f'<span>{range_label} {html_lib.escape(str(group_caption))}: {range_text}</span>'
            f'</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    slide_dir = 'ltr' if en else 'rtl'
    subtitle = ('Market pricing analysis and competitor comparison within the study scope'
                if en else 'تحليل أسعار السوق ومقارنة الوحدات المنافسة في النطاق الجغرافي')
    return f'''<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
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
        <p class="header-subtitle">{subtitle}</p>
      </div>
    </div>
  </header>
  <div style="padding:0 42px;margin-top:12px;">
    <div style="background:#f3f6f8;border:1px solid #dbe4ee;border-radius:12px;padding:14px 16px 16px;box-sizing:border-box;min-height:560px;display:flex;flex-direction:column;">
      {scope_html}
      <div style="display:grid;direction:{slide_dir};grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:'table chart';gap:20px;flex:1;overflow:visible;align-items:stretch;">
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
