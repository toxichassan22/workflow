"""Owner-uploaded, anonymized transaction worksheets for market summaries."""


def _summary_benchmark_files():
    import os
    from pathlib import Path

    configured = str(os.environ.get('MARKET_TRANSACTION_BENCHMARK_DIR') or '').strip()
    root = (Path(configured) if configured else
            Path(__file__).resolve().parent / 'market_data' / 'transaction_benchmarks')
    return sorted(root.rglob('*.xlsx')) if root.is_dir() else []


def _summary_benchmark_csv_files():
    from pathlib import Path

    root = Path(__file__).resolve().parent / 'market_data' / 'transaction_benchmarks'
    return sorted(root.glob('*.csv')) if root.is_dir() else []


def _xlsx_shared_strings(archive):
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
    except (KeyError, ET.ParseError):
        return []
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    return [''.join(node.text or '' for node in item.iter(ns + 't'))
            for item in root.findall(ns + 'si')]


def _xlsx_column_index(cell_ref):
    value = 0
    for char in str(cell_ref or ''):
        if not char.isalpha():
            break
        value = value * 26 + ord(char.upper()) - ord('A') + 1
    return max(0, value - 1)


def _xlsx_value(cell, shared_strings, ns):
    kind = cell.attrib.get('t')
    if kind == 'inlineStr':
        return ''.join(node.text or '' for node in cell.iter(ns + 't'))
    raw = cell.findtext(ns + 'v')
    if kind == 's' and raw:
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ''
    return raw or ''


def _summary_xlsx_sheets(file_path):
    """Read cell values with the standard library, without workbook mutation."""
    import xml.etree.ElementTree as ET
    from zipfile import BadZipFile, ZipFile

    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    try:
        with ZipFile(file_path) as archive:
            strings = _xlsx_shared_strings(archive)
            sheet_names = sorted(
                name for name in archive.namelist()
                if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'))
            sheets = []
            for sheet_name in sheet_names:
                try:
                    root = ET.fromstring(archive.read(sheet_name))
                except ET.ParseError:
                    continue
                rows = []
                for row in root.iter(ns + 'row'):
                    values = []
                    for cell in row.findall(ns + 'c'):
                        index = _xlsx_column_index(cell.attrib.get('r'))
                        if index >= 500:
                            continue
                        if len(values) <= index:
                            values.extend([''] * (index + 1 - len(values)))
                        values[index] = _xlsx_value(cell, strings, ns)
                    rows.append(values)
                sheets.append(rows)
            return sheets
    except (OSError, BadZipFile):
        return []


def _summary_benchmark_number(value):
    import re

    text = str(value or '').strip().translate(str.maketrans(
        '٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('٬', '').replace(',', '').replace('٫', '.')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _summary_benchmark_date(value):
    from datetime import datetime, timedelta

    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except ValueError:
        try:
            serial = float(text)
        except ValueError:
            return ''
        if not 1 <= serial <= 100000:
            return ''
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()


def _summary_sheet_records(rows):
    if not rows:
        return []
    for header_index, header in enumerate(rows[:20]):
        labels = [_fold_choice(value) for value in header]
        columns = {}
        for index, label in enumerate(labels):
            if not label:
                continue
            if 'تاريخ الصفقه' in label:
                columns['date'] = index
            elif label in ('المدينه', 'مدينه'):
                columns['city'] = index
            elif label in ('الحي', 'حي'):
                columns['district'] = index
            elif 'نوع الوحده' in label:
                columns['unit_type'] = index
            elif 'سعر المتر' in label and ('تقريب' in label or 'approx' in label):
                columns.setdefault('price_sqm', index)
            elif 'قيمه تقريبيه' in label or label in ('قيمه الصفقه', 'قيمه الصفقه كما يعرضها الموقع'):
                columns.setdefault('deal_value', index)
            elif 'مصدر الوثيقه' in label:
                columns['source'] = index
        required = {'date', 'city', 'district', 'unit_type'}
        if not required.issubset(columns) or not ({'price_sqm', 'deal_value'} & columns.keys()):
            continue
        return [
            {key: row[index] if index < len(row) else ''
             for key, index in columns.items()}
            for row in rows[header_index + 1:]
        ]
    return []


def build_summary_local_benchmarks(payload):
    import csv
    import re
    import statistics

    payload = payload if isinstance(payload, dict) else {}
    scope = normalize_summary_scope(
        payload.get('summaryScope') or payload.get('summary_scope'),
        payload.get('city'))
    bounds = payload.get('dataPeriodBounds')
    bounds = bounds if isinstance(bounds, dict) else {}
    start, end = str(bounds.get('from') or ''), str(bounds.get('to') or '')
    groups = {}
    benchmark_rows = []
    xlsx_files = _summary_benchmark_files()
    for file_path in xlsx_files:
        for sheet_rows in _summary_xlsx_sheets(file_path):
            benchmark_rows.extend(_summary_sheet_records(sheet_rows))
    for csv_path in _summary_benchmark_csv_files():
        try:
            with csv_path.open('r', encoding='utf-8-sig', newline='') as handle:
                benchmark_rows.extend(csv.DictReader(handle))
        except (OSError, csv.Error):
            continue
    for row in benchmark_rows:
        city = _norm(row.get('city'))
        city_scope = next((item for item in scope['cities']
                           if _fold_choice(item['name']) == _fold_choice(city)), None)
        if not city_scope:
            continue
        district = _norm(row.get('district'))
        if city_scope['districts'] and not any(
                _fold_choice(item) == _fold_choice(district)
                for item in city_scope['districts']):
            continue
        row_date = _summary_benchmark_date(row.get('date'))
        if (start or end) and not row_date:
            continue
        if start and row_date < start:
            continue
        if end and row_date > end:
            continue
        price_sqm = _summary_benchmark_number(
            row.get('price_sqm') or row.get('price_sqm_sar'))
        deal_value = _summary_benchmark_number(
            row.get('deal_value') or row.get('deal_value_sar'))
        if price_sqm <= 0 and deal_value <= 0:
            continue
        unit_type = _norm(row.get('unit_type')) or 'غير محدد'
        key = (city, district, unit_type)
        group = groups.setdefault(key, {
            'city': city, 'district': district, 'unit_type': unit_type,
            'record_count': 0, 'price_sqm': [], 'deal_values': [], 'dates': [],
            'sources': set(), 'source_urls': set(),
        })
        group['record_count'] += 1
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

    source_url_re = re.compile(r'https?://[^\s<>()]+', re.I)
    extracted_urls = []
    for file_path in xlsx_files:
        for rows in _summary_xlsx_sheets(file_path):
            for row in rows[:20]:
                for cell in row:
                    extracted_urls.extend(source_url_re.findall(str(cell or '')))
    workbook_source_urls = sorted(set(url.rstrip('.,؛') for url in extracted_urls))

    output = []
    for key in sorted(groups, key=lambda item: tuple(_fold_choice(value) for value in item)):
        group = groups[key]
        dates = sorted(group['dates'])
        output.append({
            'city': group['city'], 'district': group['district'],
            'unit_type': group['unit_type'],
            'deal_count_in_file': group['record_count'],
            'median_price_sqm_sar': round(statistics.median(group['price_sqm']))
            if group['price_sqm'] else None,
            'min_price_sqm_sar': round(min(group['price_sqm'])) if group['price_sqm'] else None,
            'max_price_sqm_sar': round(max(group['price_sqm'])) if group['price_sqm'] else None,
            'median_deal_value_sar': round(statistics.median(group['deal_values']))
            if group['deal_values'] else None,
            'period_from': dates[0] if dates else '', 'period_to': dates[-1] if dates else '',
            'sources': sorted(group['sources']),
            'source_urls': sorted(group['source_urls'] or set(workbook_source_urls)),
        })
    return {
        'available': bool(output),
        'scope': scope,
        'period_from': start,
        'period_to': end,
        'groups': output,
        'limitations': ('ملفات معاملات مجهولة الهوية ومحدودة بالأحياء والفئات والفترة الموجودة فيها؛ '
                        'عدد السجلات ليس تعدادًا كاملًا للسوق ولا يحدد أسماء منافسين.'),
    }
