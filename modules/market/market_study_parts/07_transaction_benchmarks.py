"""Local, anonymized transaction-price context for selected comparisons."""


def build_transaction_price_benchmarks(payload, axes):
    """Aggregate uploaded sale records without creating named competitor rows."""
    import csv
    import statistics
    from pathlib import Path

    payload = payload if isinstance(payload, dict) else {}
    scope = payload.get('competitorScope') or payload.get('competitor_scope')
    scope = scope if isinstance(scope, dict) else {}
    mode = scope.get('mode') if scope.get('mode') in ('district', 'city') else 'district'
    city = _norm(payload.get('city'))
    district = _norm(payload.get('district'))
    bounds = payload.get('dataPeriodBounds')
    bounds = bounds if isinstance(bounds, dict) else {}
    start, end = str(bounds.get('from') or ''), str(bounds.get('to') or '')
    has_residential_sale = any(
        axis.get('type') == 'residential' and axis.get('operation') == 'sale'
        for axis in (axes or []))
    groups = {}
    if has_residential_sale and city:
        data_dir = Path(__file__).resolve().parent / 'market_data' / 'transaction_benchmarks'
        for file_path in sorted(data_dir.glob('*.csv')):
            try:
                with file_path.open('r', encoding='utf-8-sig', newline='') as handle:
                    for row in csv.DictReader(handle):
                        if _fold_choice(row.get('city')) != _fold_choice(city):
                            continue
                        row_district = _norm(row.get('district'))
                        if mode == 'district' and _fold_choice(row_district) != _fold_choice(district):
                            continue
                        row_date = str(row.get('date') or '')
                        if start and row_date and row_date < start:
                            continue
                        if end and row_date and row_date > end:
                            continue
                        try:
                            price_sqm = float(row.get('price_sqm_sar') or 0)
                            deal_value = float(row.get('deal_value_sar') or 0)
                        except (TypeError, ValueError):
                            continue
                        if price_sqm <= 0 and deal_value <= 0:
                            continue
                        unit_type = _norm(row.get('unit_type')) or 'غير محدد'
                        key = (row_district, unit_type)
                        group = groups.setdefault(key, {
                            'district': row_district, 'unit_type': unit_type,
                            'price_sqm': [], 'deal_values': [], 'dates': [],
                            'sources': set(), 'source_urls': set(),
                        })
                        if price_sqm > 0:
                            group['price_sqm'].append(price_sqm)
                        if deal_value > 0:
                            group['deal_values'].append(deal_value)
                        if row_date:
                            group['dates'].append(row_date)
                        if row.get('source'):
                            group['sources'].add(_norm(row.get('source')))
                        if row.get('source_url'):
                            group['source_urls'].add(_norm(row.get('source_url')))
            except (OSError, csv.Error):
                continue

    output_groups = []
    for key in sorted(groups, key=lambda item: (_fold_choice(item[0]), _fold_choice(item[1]))):
        group = groups[key]
        dates = sorted(group['dates'])
        output_groups.append({
            'district': group['district'],
            'unit_type': group['unit_type'],
            'deal_count': max(len(group['price_sqm']), len(group['deal_values'])),
            'median_price_sqm_sar': round(statistics.median(group['price_sqm']))
            if group['price_sqm'] else None,
            'min_price_sqm_sar': round(min(group['price_sqm'])) if group['price_sqm'] else None,
            'max_price_sqm_sar': round(max(group['price_sqm'])) if group['price_sqm'] else None,
            'median_deal_value_sar': round(statistics.median(group['deal_values']))
            if group['deal_values'] else None,
            'period_from': dates[0] if dates else '',
            'period_to': dates[-1] if dates else '',
            'sources': sorted(group['sources']),
            'source_urls': sorted(group['source_urls']),
        })
    covered = sorted({group['district'] for group in output_groups}, key=_fold_choice)
    scope_name = district if mode == 'district' else city
    note = ('هذه صفقات مرجعية مجهولة الهوية؛ لا تمثل مشاريع منافسة مسماة ولا تُحتسب ضمن عدد المنافسين. '
            'نطاق المدينة يعرض الأحياء الموجودة في ملفات البيانات فقط، ولا يمثل تغطية كاملة للمدينة.')
    if not output_groups:
        note = 'لا توجد صفقات بيع سكنية مطابقة للمدينة والحي وفترة البيانات المحددة.'
    return {
        'available': bool(output_groups),
        'scope_mode': mode,
        'scope_name': scope_name,
        'city': city,
        'covered_districts': covered,
        'period_from': start,
        'period_to': end,
        'groups': output_groups,
        'note': note,
        'source': 'صفقات عقارية واردة في ملفات البيانات المرفوعة، بمصادرها الأصلية',
        'source_url': 'https://rei.rega.gov.sa/ar/advanced-search/deals',
    }
