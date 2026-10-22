# Input parsing for the financial cost waterfall.
#
# The waterfall is a composition of the cost table.  Reading "the last positive
# number in the row" made a zero-output row contribute its duration or its
# rate instead of its cost, so the chart showed values that exist nowhere in
# the study.  The helpers here read the named output column, skip total rows and
# return the study's own totals.

_WATERFALL_NAME_HEADER_RE = re.compile(
    r'(?:اسم|البند|البيان|name|item|description)', re.IGNORECASE)
_WATERFALL_VALUE_HEADER_RE = re.compile(
    r'(?:الناتج|إجمالي|اجمالي|القيمة|المبلغ|التكلفة|المجموع|output|amount|value|total|cost)',
    re.IGNORECASE)
_WATERFALL_NOT_VALUE_HEADER_RE = re.compile(
    r'(?:نسبة|مدة|كمية|سعر|%|quantity|duration|rate|price)', re.IGNORECASE)
_WATERFALL_MONEY_RE = re.compile(r'(?:ر\.?\s*س|ريال|SAR)', re.IGNORECASE)

_WATERFALL_TOTAL_NAMES = frozenset({
    'الإجمالي', 'الاجمالي', 'إجمالي', 'اجمالي', 'المجموع', 'مجموع', 'Total', 'total',
    'إجمالي تكلفة المشروع', 'اجمالي تكلفة المشروع', 'إجمالي تكلفة الاستثمار',
    'اجمالي تكلفة الاستثمار', 'إجمالي التكاليف', 'اجمالي التكاليف', 'مجموع التكاليف',
    'تكلفة المشروع', 'تكلفة الاستثمار',
})


def _waterfall_column_indexes(headers):
    """Return (name_index, value_index) for a report table's headers."""
    headers = [str(header or '').strip() for header in (headers or [])]
    name_idx = 0
    value_idx = None
    for index, text in enumerate(headers):
        if not text:
            continue
        if _WATERFALL_NAME_HEADER_RE.search(text) and not _WATERFALL_VALUE_HEADER_RE.search(text):
            name_idx = index
        if (_WATERFALL_VALUE_HEADER_RE.search(text)
                and not _WATERFALL_NOT_VALUE_HEADER_RE.search(text)
                and not _WATERFALL_NAME_HEADER_RE.search(text)):
            if value_idx is None or 'الناتج' in text:
                value_idx = index
    return name_idx, value_idx


def _waterfall_normalized_name(name):
    text = re.sub(r'[إأآٱ]', 'ا', str(name or '')).strip()
    return re.sub(r'\s+', ' ', text)


def _waterfall_is_total_name(name):
    text = _waterfall_normalized_name(name)
    if text in _WATERFALL_TOTAL_NAMES or text.lower() in ('total', 'grand total'):
        return True
    return bool(re.fullmatch(
        r'(?:ال)?(?:اجمالي|مجموع|total)'
        r'(?: (?:العام|الكلي|للمشروع|للتكاليف|للتكلفة|تكلفة المشروع|تكاليف المشروع|'
        r'تكلفة الاستثمار|تكاليف الاستثمار))?',
        text, re.IGNORECASE))


def _waterfall_row_name(row, name_idx=0):
    if isinstance(row, dict):
        for key in ('اسم التكلفة', 'البند', 'الاسم', 'البيان', 'name', 'item', 'description'):
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ''
    if isinstance(row, (list, tuple)) and row:
        index = name_idx if isinstance(name_idx, int) and 0 <= name_idx < len(row) else 0
        return str(row[index] or '').strip()
    return ''


def _waterfall_row_value(row, value_idx=None):
    """The row's cost value, read from the named output column when there is one."""
    if isinstance(row, dict):
        for key in ('الناتج', 'الإجمالي', 'القيمة', 'المبلغ', 'output', 'amount', 'value', 'total', 'cost'):
            if key not in row:
                continue
            raw = row.get(key)
            if raw is None or str(raw).strip() in ('', '—', '-', 'N/A'):
                continue
            return _clean_numeric_val(raw)
        return 0.0
    if not isinstance(row, (list, tuple)) or not row:
        return 0.0
    if isinstance(value_idx, int) and 0 <= value_idx < len(row):
        return _clean_numeric_val(row[value_idx])
    # No header available: never take a percentage cell, and prefer a cell that
    # is plainly money over a duration or a count.
    fallback = 0.0
    for index in range(len(row) - 1, 0, -1):
        cell = str(row[index] or '').strip()
        if not cell or cell in ('—', '-', 'N/A') or '%' in cell or '٪' in cell:
            continue
        value = _clean_numeric_val(cell)
        if value <= 0:
            continue
        if _WATERFALL_MONEY_RE.search(cell) or ',' in cell:
            return value
        if fallback <= 0:
            fallback = value
    return fallback


def _waterfall_positive_number(*values):
    for value in values:
        number = _clean_numeric_val(value)
        if number > 0:
            return number
    return 0.0


def _waterfall_model_totals(model, project_data=None):
    """(adjusted, with_finance, project) totals as calculated by the study itself."""
    model = model if isinstance(model, dict) else {}
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    calc = _parse_financial_dict((project_data or {}).get('financial_calc_data'))
    adjusted = _waterfall_positive_number(
        projection.get('adjustedProjectCost'), inputs.get('adjustedProjectCost'),
        calc.get('adjustedProjectCost'))
    with_finance = _waterfall_positive_number(
        projection.get('projectCostWithFinance'), inputs.get('projectCostWithFinance'),
        calc.get('projectCostWithFinance'))
    project = _waterfall_positive_number(
        projection.get('projectCost'), inputs.get('projectCost'), calc.get('projectCost'))
    return adjusted, with_finance, project
