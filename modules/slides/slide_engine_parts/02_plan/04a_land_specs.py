"""Land specification extraction and rendering."""

LAND_SPEC_REPEATED_FLOOR_COUNT = 18


def _land_specs_number_text(value):
    if value in (None, '', '—'):
        return '—'
    try:
        number = Decimal(str(value).replace(',', '').strip())
        if not number.is_finite():
            return str(value)
        text = format(number, 'f')
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if Decimal(text) == 0:
        text = '0'
    sign = '-' if text.startswith('-') else ''
    whole, separator, fraction = (text[1:] if sign else text).partition('.')
    return sign + f'{int(whole or 0):,}' + (separator + fraction if separator else '')


def _land_specs_area_display(value):
    if value in (None, '', '—'):
        return '—'
    return f'{_land_specs_number_text(value)} م²'


def _has_land_specs_data(project_data):
    """Return whether the project has enough regulatory or land specification facts."""
    source = project_data if isinstance(project_data, dict) else {}
    project_spec_keys = (
        'croquis_land_area', 'approved_financial_area', 'land_area', 'total_land_area',
        'plot_number', 'plan_number', 'deed_number', 'deed_date', 'approved_floor_count',
        'approved_coverage_ratio', 'approved_typical_floor_coverage',
        'approved_floor_area_ratio', 'building_ratio_coverage', 'building_ratio_setbacks', 'far', 'setbacks',
        'max_floors_height', 'allowed_uses', 'building_system', 'parking_regulations',
    )
    if any(str(source.get(k) or '').strip() for k in project_spec_keys):
        return True
    document_spec_keys = (
        'croquis_land_area', 'land_area', 'total_land_area', 'plot_number', 'plan_number',
        'deed_number', 'deed_date', 'building_ratio_coverage', 'building_ratio_setbacks',
        'far', 'floor_area_ratio', 'setbacks', 'max_floors_height', 'max_floors',
        'allowed_uses', 'permitted_uses', 'building_system', 'parking_regulations',
    )
    doc_raw = source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis')
    if doc_raw:
        doc = _decode_json_fact(doc_raw) if isinstance(doc_raw, (str, dict)) else {}
        if isinstance(doc, dict):
            if any(str(doc.get(k) or '').strip() for k in document_spec_keys):
                return True
            parcels = doc.get('parcels')
            if isinstance(parcels, list) and any(
                    isinstance(p, dict) and any(str(p.get(k) or '').strip() for k in document_spec_keys)
                    for p in parcels):
                return True
    return False


def _extract_land_specs_data(project_data):
    """Extract land specifications and regulatory conditions into a clean dictionary."""
    source = project_data if isinstance(project_data, dict) else {}
    doc_raw = source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis')
    doc = _decode_json_fact(doc_raw) if isinstance(doc_raw, (str, dict)) else {}
    if not isinstance(doc, dict):
        doc = {}
    parcels = doc.get('parcels') if isinstance(doc.get('parcels'), list) else []
    first_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}

    def _val(*keys, fallback='—'):
        for k in keys:
            v = source.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
            v = doc.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
            v = first_parcel.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
        return fallback

    plot_num = _val('plot_number', 'plotNumber', 'parcel_number')
    plan_num = _val('plan_number', 'planNumber')
    deed_num = _val('deed_number', 'deedNumber', 'instrument_number')
    deed_dt = _val('deed_date', 'deedDate', 'instrument_date')

    land_area = _val('approved_financial_area', 'croquis_land_area', 'land_area', 'total_land_area')
    built_area = _val('built_area', 'total_built_area', 'building_area')
    city = _val('city')
    district = _val('district')

    approved_coverage = str(source.get('approved_coverage_ratio') or '').strip()
    approved_typical_coverage = str(source.get('approved_typical_floor_coverage') or '').strip()
    approved_floor_count = str(source.get('approved_floor_count') or '').strip() or '—'
    bldg_ratio = approved_coverage or _val(
        'building_ratio_coverage', 'building_ratio_setbacks', 'building_ratio', fallback='60% كحد أقصى')
    if bldg_ratio and not bldg_ratio.endswith('%') and _financial_number(bldg_ratio) > 0:
        bldg_ratio += '%'
    if approved_typical_coverage and not approved_typical_coverage.endswith('%'):
        approved_typical_coverage += '%'
    far = _val('approved_floor_area_ratio', 'far', 'nsba_albna__far', 'floor_area_ratio')
    area_number = _financial_number(land_area)
    far_number = _financial_number(far)
    coverage_number = _financial_number(approved_coverage)
    total_built_area = area_number * far_number if area_number > 0 and far_number > 0 else None
    coverage_area = area_number * coverage_number / 100 if area_number > 0 and coverage_number > 0 else None
    repeated_floors_area = (
        max(total_built_area - coverage_area, 0)
        if total_built_area is not None and coverage_area is not None else None
    )
    typical_floor_area = (
        repeated_floors_area / LAND_SPEC_REPEATED_FLOOR_COUNT
        if repeated_floors_area is not None else None
    )
    setbacks = _val('setbacks', 'building_setbacks', fallback='حسب كود البناء والاشتراطات البلدية')
    max_floors = _val('max_floors_height', 'max_floors', 'max_height', 'floors_allowed')
    allowed_uses = _val('allowed_uses', 'permitted_uses', 'zoning', 'land_use', fallback='تجاري / سكني استثماري')
    bldg_system = _val('building_system', 'regulatory_constraints')
    parking = _val('parking_regulations', 'parking_spaces', fallback='حسب اشتراطات كود البناء السعودي ومعايير الأمانة')
    infrastructure = _val('infrastructure', 'utilities', fallback='مكتملة الخدمات (كهرباء، مياه، اتصالات، إنارة)')

    return {
        'plot_number': plot_num,
        'plan_number': plan_num,
        'deed_number': deed_num,
        'deed_date': deed_dt,
        'land_area': land_area,
        'built_area': built_area,
        'approved_floor_count': approved_floor_count,
        'approved_coverage_ratio': approved_coverage or '—',
        'approved_typical_floor_coverage': approved_typical_coverage or '—',
        'city': city,
        'district': district,
        'building_ratio_coverage': bldg_ratio,
        'far': far,
        'computed_total_built_area': total_built_area,
        'computed_coverage_area': coverage_area,
        'computed_repeated_floors_area': repeated_floors_area,
        'computed_typical_floor_area': typical_floor_area,
        'setbacks': setbacks,
        'max_floors_height': max_floors,
        'allowed_uses': allowed_uses,
        'building_system': bldg_system,
        'parking_regulations': parking,
        'infrastructure': infrastructure,
    }


def _build_land_specs_slide(slide, project_data, branding=None, slide_num=None, total_slides=None):
    """Render land specifications and regulatory conditions as an editorial analytical slide."""
    source = project_data if isinstance(project_data, dict) else {}
    specs = _extract_land_specs_data(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مواصفات الأرض والاشتراطات التنظيمية'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    land_area_fmt = specs['land_area']
    if land_area_fmt != '—' and 'م' not in land_area_fmt:
        land_area_fmt = _land_specs_number_text(land_area_fmt) + ' م²'

    top_metric_cards = [
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">مساحة الأرض التنظيمية</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(land_area_fmt)}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">نسبة التغطية والبناء</div>'
        f'<div style="font-size:17px;font-weight:800;color:{accent};margin-top:2px;">{html_lib.escape(specs["building_ratio_coverage"])}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">معامل البناء (FAR)</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(specs["far"])}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">الأدوار المعتمدة</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(specs["approved_floor_count"])}</div></div>',
    ]
    metrics_strip = f'<div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:14px;margin-bottom:16px;">{"".join(top_metric_cards)}</div>'

    doc_rows = [
        ('رقم الصك وتاريخه', f"صك رقم {specs['deed_number']} — تاريخ {specs['deed_date']}" if specs['deed_number'] != '—' else '—'),
        ('رقم المخطط والقطعة', f"مخطط رقم {specs['plan_number']} / قطعة رقم {specs['plot_number']}" if specs['plot_number'] != '—' else '—'),
        ('المدينة والحي', f"{specs['city']} — حي {specs['district']}" if specs['city'] != '—' else '—'),
        ('الاستخدامات المصرحة', specs['allowed_uses']),
        ('البنية التحتية والخدمات', specs['infrastructure']),
    ]
    doc_table_html = ''.join(
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;">'
        f'<div style="font-weight:700;color:#64748b;min-width:140px;">{label}</div>'
        f'<div style="font-weight:700;color:{primary};text-align:left;flex:1;">{html_lib.escape(val)}</div>'
        f'</div>' for label, val in doc_rows
    )

    reg_rows = [
        ('تغطية الطوابق المتكررة', specs['approved_typical_floor_coverage']),
        ('الحد الأقصى التنظيمي للارتفاع / الأدوار', specs['max_floors_height']),
        ('الارتدادات النظامية', specs['setbacks']),
        ('نظام البناء والاشتراطات', specs['building_system']),
        ('اشتراطات المواقف والمداخل', specs['parking_regulations']),
        ('إجمالي مسطحات البناء', _land_specs_area_display(specs['computed_total_built_area'])),
        ('مساحة البناء', _land_specs_area_display(specs['computed_coverage_area'])),
        ('مساحة الأدوار المتكررة', _land_specs_area_display(specs['computed_repeated_floors_area'])),
        ('مساحة الدور', _land_specs_area_display(specs['computed_typical_floor_area'])),
        ('مساحة البناء الموثقة بالمستندات', specs['built_area']),
    ]
    reg_table_html = ''.join(
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:11px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;">'
        f'<div style="font-weight:700;color:#64748b;min-width:150px;">{label}</div>'
        f'<div style="font-weight:700;color:{primary};text-align:left;flex:1;">{html_lib.escape(val)}</div>'
        f'</div>' for label, val in reg_rows
    )

    columns_html = f'''<div style="display:grid;grid-template-columns:1.05fr 0.95fr;gap:18px;height:385px;">
      <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;box-sizing:border-box;">
        <div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid {primary};">المحددات التوثيقية والمساحية</div>
        {doc_table_html}
      </div>
      <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;box-sizing:border-box;">
        <div style="font-size:15px;font-weight:800;color:{accent};margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid {accent};">الاشتراطات والضوابط التنظيمية</div>
        {reg_table_html}
      </div>
    </div>'''

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">LAND SPECIFICATIONS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">المحددات التوثيقية والمساحية والاشتراطات والضوابط العمرانية للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    {metrics_strip}
    {columns_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">مواصفات واشتراطات الأرض</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''
