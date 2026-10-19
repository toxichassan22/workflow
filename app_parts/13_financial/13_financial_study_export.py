


def _financial_report_escape(value):
    if value is None or value == '':
        return '—'
    if isinstance(value, (dict, list)):
        # A JSON dump used to be emitted here, which put raw [{"year":4,...}] into the client PDF.
        # Structured values belong in their own table, never in a label/value row.
        return '—'
    return html_lib.escape(str(value))


_FINANCIAL_NUMERIC_CELL = re.compile(r'^[\s\-+()0-9.,%٠-٩٬٫]+$')


def _financial_report_cell(rendered, value=None):
    """A figure is an LTR run, so it needs an LTR cell.

    In an RTL cell the bidi algorithm has no strong direction to attach the leading sign to and
    gives it the paragraph direction, so `-13,125,000` printed as `13,125,000-`.
    """
    text = str(value if value is not None else rendered).strip()
    if text and any(char.isdigit() for char in text) and _FINANCIAL_NUMERIC_CELL.match(text):
        return f'<td dir="ltr">{rendered}</td>'
    return f'<td>{rendered}</td>'


_FINANCIAL_PERCENT_KEYS = {
    'coverageRate', 'occupancy', 'costPct', 'devPct', 'drawPct', 'repaymentPct', 'murabahaPct',
    'growth', 'occupancyReach', 'reachPct', 'financingRate', 'annualFinanceRate',
    'developerRate', 'financeArrangementFeeRate', 'fundManagementRate',
    'operatingExitCostRate', 'developerUpliftShare', 'roi', 'projectIrr', 'equityIrr',
}
_FINANCIAL_YEAR_KEYS = {
    'year', 'startYear', 'endYear', 'studyYear', 'operationYear', 'developmentYears',
    'operationYears', 'salesStartYear', 'salesYears', 'landContributionYear',
    'financeDrawYears', 'financeRepaymentStartYear', 'financeRepaymentYears',
    'financeMurabahaStartYear', 'financeMurabahaYears',
    'fundFeeStartYear', 'fundFeeEndYear', 'performanceCrystallizationYear',
    'saleExitYear', 'operatingExitYear',
}


def _financial_report_plain_number(value):
    if isinstance(value, bool) or value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text == '—':
        return None
    cleaned = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٬،', '0123456789,,'))
    cleaned = cleaned.replace('%', '').replace('سنة', '').replace('م²', '').replace(' ', '')
    cleaned = cleaned.replace('(', '-').replace(')', '')
    cleaned = cleaned.replace('٫', '.')
    cleaned = cleaned.replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _round_financial_hundredth(value):
    try:
        val = float(value)
        if not math.isfinite(val):
            return value
        return (-1 if val < 0 else 1) * math.floor(abs(val) * 100 + 0.5 + 1e-9) / 100
    except (ValueError, TypeError):
        return value


def _financial_exact_text(value, grouped=True):
    from numeric_precision import format_precise_number
    return format_precise_number(_round_financial_hundredth(value), grouped=grouped)


def _financial_report_format_number(value, key=''):
    number = _financial_report_plain_number(value)
    if number is None:
        return _financial_report_escape(value)
    if isinstance(value, str) and value.strip() and not _FINANCIAL_DISPLAY_VALUE_RE.fullmatch(value.strip()):
        # Compound text such as «سنة و6 شهور و12 يوم» renders verbatim — extracting the first
        # digit used to collapse the whole duration into «6 سنة».
        return _financial_report_escape(value)
    field = str(key or '')
    if field in _FINANCIAL_PERCENT_KEYS or (isinstance(value, str) and '%' in str(value)):
        if field in {'roi', 'projectIrr', 'equityIrr', 'irr'} and isinstance(value, (int, float)):
            display = number * 100
        elif field in {'occupancyReach'} and abs(number) <= 1:
            display = number * 100
        else:
            display = number
        return html_lib.escape(_financial_exact_text(display, grouped=False) + '%')
    if field in {'payback', 'equityPayback'} or (isinstance(value, str) and 'سنة' in str(value)):
        return html_lib.escape(_financial_exact_text(number, grouped=False) + ' سنة')
    if field in _FINANCIAL_YEAR_KEYS and float(number).is_integer() and abs(number) < 10000:
        return html_lib.escape(str(int(number)))
    return html_lib.escape(_financial_exact_text(number))


_FINANCIAL_DISPLAY_VALUE_RE = re.compile(
    r'^\s*(?P<open>\()?\s*(?P<number>[-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*|[0-9٠-٩]+)(?:[٫.][0-9٠-٩]+)?)'
    r'\s*(?P<close>\))?\s*(?P<suffix>%|٪|سنة|سنوات|م²|م2|ر\.?\s?س|ريال(?:\s+سعودي)?)?\s*$'
)
_FINANCIAL_PERCENT_CONTEXT_RE = re.compile(r'%|نسبة|معدل|إشغال|ROI|IRR', re.IGNORECASE)
_FINANCIAL_YEAR_CONTEXT_RE = re.compile(r'سنة|سنوات|عام|year', re.IGNORECASE)
_FINANCIAL_LITERAL_CONTEXT_RE = re.compile(
    r'تاريخ|هاتف|جوال|وثيقة|معرف|رقم|date|phone|mobile|document|identifier|\bid\b', re.IGNORECASE
)
_FINANCIAL_AMOUNT_CONTEXT_RE = re.compile(
    r'إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|'
    r'أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance', re.IGNORECASE
)
_FINANCIAL_GROUP_CONTEXT_RE = re.compile(
    r'إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|تمويل|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|'
    r'أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance', re.IGNORECASE
)
_FINANCIAL_NUMBER_TOKEN_RE = re.compile(
    r'(?<![0-9٠-٩])[-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*)(?:[٫.][0-9٠-٩]+)?(?![0-9٠-٩])'
)


def _financial_report_format_display(value, context=''):
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return _financial_report_escape(value)
    text = str(value).strip()
    context_text = str(context or '')
    if _FINANCIAL_LITERAL_CONTEXT_RE.search(context_text):
        return _financial_report_escape(value)
    match = _FINANCIAL_DISPLAY_VALUE_RE.fullmatch(text)
    if match:
        number = _financial_report_plain_number(text)
        if number is None:
            return _financial_report_escape(value)
        suffix = match.group('suffix') or ''
        amount = bool(_FINANCIAL_AMOUNT_CONTEXT_RE.search(context_text))
        percent = bool(suffix in {'%', '٪'} or (not amount and _FINANCIAL_PERCENT_CONTEXT_RE.search(context_text)))
        year = bool(suffix in {'سنة', 'سنوات'} or (not amount and _FINANCIAL_YEAR_CONTEXT_RE.search(context_text)))
        formatted = _financial_exact_text(number, grouped=not (percent or year))
        if match.group('open') and match.group('close'):
            formatted = f'({formatted.lstrip("-")})'
        if suffix:
            formatted += (' ' if suffix not in {'%', '٪'} else '') + suffix
        return html_lib.escape(formatted)
    if not (_FINANCIAL_GROUP_CONTEXT_RE.search(context_text)
            or re.search(r'م²|م2|ر\.?\s?س|ريال(?:\s+سعودي)?|SAR', text, re.IGNORECASE)):
        return _financial_report_escape(value)

    def format_token(token_match):
        raw = token_match.group(0)
        number = _financial_report_plain_number(raw)
        if number is None:
            return raw
        if 1900 <= abs(number) <= 2100 and _FINANCIAL_YEAR_CONTEXT_RE.search(context_text):
            return raw
        trailing = text[token_match.end():].lstrip()
        return _financial_exact_text(number, grouped=not trailing.startswith(('%', '٪')))

    return html_lib.escape(_FINANCIAL_NUMBER_TOKEN_RE.sub(format_token, text))


# Section 12 is a results summary with curated metrics. English acronyms (ROI, Project IRR, Equity IRR, NOI)
# are preserved directly per business domain standards.
FINANCIAL_RESULT_LABELS = (
    ('projectCost', 'إجمالي تكلفة المشروع'),
    ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
    ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
    ('developerCost', 'أتعاب المطور'),
    ('landRent', 'إيجار الأرض السنوي'),
    ('saleRevenueTotal', 'إجمالي إيرادات البيع'),
    ('revenueY1', 'إيرادات السنة الأولى'),
    ('opexY1', 'مصروفات السنة الأولى'),
    ('noiY1', 'NOI — السنة الأولى'),
    ('fullOccupancyRevenue', 'الإيرادات عند الإشغال المستهدف'),
    ('fullOccupancyNOI', 'NOI عند الإشغال المستهدف'),
    ('totalGraceDiscount', 'إجمالي خصم فترة السماح'),
    ('facilityAmount', 'قيمة التسهيل التمويلي'),
    ('arrangementFee', 'رسوم ترتيب التمويل'),
    ('totalFinanceInterest', 'إجمالي المرابحة'),
    ('totalFinanceCost', 'إجمالي كلفة التمويل'),
    ('totalFundFees', 'إجمالي أتعاب الصندوق'),
    ('saleExitValue', 'صافي التخارج البيعي'),
    ('operatingExitValue', 'صافي التخارج التشغيلي'),
    ('terminal', 'إجمالي قيمة التخارج'),
    ('landEquityContribution', 'مساهمة الأرض العينية'),
    ('totalCashEquity', 'حقوق الملكية النقدية'),
    ('totalEquityRequired', 'إجمالي حقوق الملكية المطلوبة'),
    ('totalEquityDistributions', 'إجمالي التوزيعات'),
    ('roi', 'ROI'),
    ('projectIrr', 'Project IRR'),
    ('equityIrr', 'Equity IRR'),
    ('payback', 'فترة استرداد رأس المال'),
    ('equityPayback', 'فترة استرداد حقوق الملكية'),
)


def _filter_financial_results(inputs, projection):
    inputs = inputs if isinstance(inputs, dict) else {}
    projection = projection if isinstance(projection, dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    finance_on = inputs.get('financeEnabled') == 'yes'
    fund_on = inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes'
    grace_on = rental_on and inputs.get('graceEnabled') == 'yes'
    exit_on = inputs.get('exitEnabled') == 'yes'

    def has_nonzero(val):
        num = _financial_report_plain_number(val)
        return num is not None and abs(num) > 0.0001

    land_in_kind = inputs.get('landContributionType') == 'inKind' or has_nonzero(projection.get('landEquityContribution'))
    has_land_rent = inputs.get('landStatus') == 'leased' or has_nonzero(projection.get('landRent')) or has_nonzero(inputs.get('annualLandRent'))

    allowed_keys = {'projectCost', 'developerCost', 'totalEquityRequired', 'roi', 'projectIrr', 'payback'}

    if finance_on:
        allowed_keys.update({'projectCostWithFinance', 'facilityAmount', 'arrangementFee', 'totalFinanceInterest', 'totalFinanceCost', 'totalCashEquity', 'equityIrr', 'equityPayback'})
    if finance_on or fund_on:
        allowed_keys.add('adjustedProjectCost')
    if has_land_rent:
        allowed_keys.add('landRent')
    if sales_on:
        allowed_keys.add('saleRevenueTotal')
    if rental_on:
        allowed_keys.update({'revenueY1', 'opexY1', 'noiY1', 'fullOccupancyRevenue', 'fullOccupancyNOI'})
    if grace_on:
        allowed_keys.add('totalGraceDiscount')
    if fund_on:
        allowed_keys.add('totalFundFees')
    if exit_on:
        allowed_keys.add('terminal')
        if sales_on:
            allowed_keys.add('saleExitValue')
        if rental_on:
            allowed_keys.add('operatingExitValue')
    if land_in_kind:
        allowed_keys.add('landEquityContribution')
    if has_nonzero(projection.get('totalEquityDistributions')):
        allowed_keys.add('totalEquityDistributions')

    result = []
    for key, label in FINANCIAL_RESULT_LABELS:
        if key not in allowed_keys:
            continue
        val = projection.get(key)
        if val in (None, '', [], {}) and inputs.get(key) not in (None, ''):
            val = inputs.get(key)
        if val in (None, '', [], {}):
            continue
        result.append((label, val, key))
    return result


def _filter_cashflow_columns(rows, inputs):
    if not isinstance(rows, list) or not rows:
        return rows
    inputs = inputs if isinstance(inputs, dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    finance_on = inputs.get('financeEnabled') == 'yes'
    fund_on = inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes'
    grace_on = rental_on and inputs.get('graceEnabled') == 'yes'
    exit_on = inputs.get('exitEnabled') == 'yes'

    drop_columns = set(FINANCIAL_REPORT_DROP_COLUMNS)
    if not sales_on:
        drop_columns.update({'saleRevenue', 'المبيعات', 'saleExit', 'saleExitGross'})
    if not rental_on:
        drop_columns.update({'operatingRevenue', 'إيرادات التأجير', 'opex', 'المصروفات', 'noi', 'NOI', 'operatingExit', 'operatingExitGross', 'occupancyReach', 'الوصول للإشغال %'})
    if not grace_on:
        drop_columns.update({'graceDiscount', 'خصم فترة السماح'})
    if not fund_on:
        drop_columns.update({'fundFeesAnnual', 'أتعاب الصندوق', 'fundManagementFee', 'additionalFundFees', 'fundExitFee', 'performanceFee'})
    if not finance_on:
        drop_columns.update({'financeDraw', 'سحب التمويل', 'financeInterest', 'فائدة التمويل', 'مرابحة التمويل', 'financeFee', 'رسوم التمويل', 'financeRepayment', 'سداد أصل التمويل', 'openingDebt', 'closingDebt', 'فائدة ورسوم التمويل', 'مرابحة ورسوم التمويل'})
    if not exit_on:
        drop_columns.update({'terminal', 'قيمة التخارج', 'saleExit', 'operatingExit'})

    filtered_rows = []
    for row in rows:
        if isinstance(row, dict):
            filtered_rows.append({k: v for k, v in row.items() if k not in drop_columns and FINANCIAL_COLUMN_LABELS.get(k, k) not in drop_columns})
        else:
            filtered_rows.append(row)
    return filtered_rows


def _financial_report_rows(rows):
    visible = []
    for item in rows:
        if len(item) == 3:
            label, value, key = item
        else:
            label, value = item
            key = ''
        if value in (None, '', [], {}) or isinstance(value, (dict, list)):
            continue
        visible.append((label, value, key))
    if not visible:
        return '<p class="empty">لا توجد قيم مطبقة في هذا القسم.</p>'
    return '<table class="summary-table"><tbody>' + ''.join(
        f'<tr><th>{_financial_report_escape(label)}</th>'
        + _financial_report_cell(_financial_report_format_number(value, key)) + '</tr>'
        for label, value, key in visible
    ) + '</tbody></table>'


FINANCIAL_COLUMN_LABELS = {
    'name': 'البند', 'useType': 'نوع الاستخدام', 'units': 'عدد الوحدات',
    'unitArea': 'مساحة الوحدة م²', 'builtArea': 'المساحة المبنية م²',
    'revenueArea': 'المساحة البيعية/التأجيرية م²', 'investmentModel': 'نموذج الاستفادة',
    'component': 'المكون المرتبط', 'qtySource': 'مصدر الكمية', 'method': 'طريقة الحساب',
    'qty': 'الكمية / المساحة', 'price': 'السعر / النسبة', 'period': 'الفترة',
    'occupancy': 'الإشغال المستهدف %', 'class': 'التصنيف', 'duration': 'المدة',
    'year': 'السنة', 'costPct': 'نسبة تكلفة التطوير %', 'devPct': 'نسبة دفعة المطور %',
    'drawPct': 'نسبة السحب %', 'repaymentPct': 'نسبة السداد %', 'murabahaPct': 'نسبة المرابحة %',
    'value': 'المبلغ / النسبة', 'startYear': 'سنة البداية', 'endYear': 'سنة النهاية',
    'recurrence': 'التكرار', 'type': 'نوع البند', 'base': 'القيمة الأساسية', 'growth': 'النمو %',
    'amount': 'القيمة', 'phase': 'المرحلة', 'occupancyReach': 'الوصول للإشغال %',
    'saleRevenue': 'المبيعات', 'operatingRevenue': 'إيرادات التأجير',
    'noi': 'NOI',
    'graceDiscount': 'خصم فترة السماح', 'developmentCost': 'تكلفة التطوير',
    'developerPayment': 'دفعة المطور', 'opex': 'المصروفات', 'landRent': 'إيجار الأرض',
    'fundFeesAnnual': 'أتعاب الصندوق', 'financeDraw': 'سحب التمويل',
    'financeInterest': 'مرابحة التمويل', 'financeFee': 'رسوم التمويل',
    'financeRepayment': 'سداد أصل التمويل', 'final': 'صافي تدفق المشروع',
    'cumulative': 'الرصيد التراكمي', 'cashReserve': 'السيولة',
    'openingDebt': 'الرصيد الافتتاحي', 'closingDebt': 'الرصيد الختامي',
    'fundManagementFee': 'أتعاب الإدارة', 'additionalFundFees': 'الأتعاب الإضافية',
    'fundExitFee': 'أتعاب التخارج', 'performanceFee': 'حافز الأداء',
    'operationYear': 'سنة التشغيل', 'studyYear': 'السنة في الدراسة', 'reachPct': 'نسبة الوصول %',
    'terminal': 'قيمة التخارج',
    'key': 'المتغير', 'low': 'متحفظ', 'high': 'متفائل',
    'scenario': 'السيناريو', 'totalRevenue': 'إجمالي الإيرادات',
    'fullOccupancyNOI': 'NOI عند الإشغال المستهدف', 'investmentCost': 'إجمالي تكلفة الاستثمار',
    'netProfit': 'صافي الربح', 'exitValue': 'قيمة التخارج', 'roi': 'ROI',
    'projectIrr': 'Project IRR', 'equityIrr': 'Equity IRR', 'payback': 'فترة الاسترداد',
    'equityRequired': 'إجمالي حقوق الملكية',
    'cashEquityRequired': 'الضخ النقدي المطلوب',
}

FINANCIAL_REPORT_DROP_COLUMNS = {
    'ترتيب / حذف', 'حذف', 'ترتيب', 'مرتبط بمكون', 'المكون المرتبط',
    'idx', 'id', 'component', 'componentId', 'leasable', 'totalArea',
    'projected', 'cashflows', 'projectCashflows', 'financePlan', 'financeRepaymentPlan', 'financeMurabahaPlan',
    'modeFlags', 'areaState',
}


def _financial_report_table(rows):
    if not isinstance(rows, list) or not rows:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    keys = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                label = FINANCIAL_COLUMN_LABELS.get(key, key)
                if key in FINANCIAL_REPORT_DROP_COLUMNS or label in FINANCIAL_REPORT_DROP_COLUMNS:
                    continue
                if key not in keys:
                    keys.append(key)
    if not keys:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    headers = ''.join(
        f'<th>{_financial_report_escape(FINANCIAL_COLUMN_LABELS.get(key, key))}</th>' for key in keys)
    body = ''.join('<tr>' + ''.join(_financial_report_cell(_financial_report_format_number(row.get(key), key)) for key in keys) + '</tr>'
                   for row in rows if isinstance(row, dict))
    return f'<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'


def _financial_screen_parts(model):
    """The study as the screen sent it, or None for a draft saved before that was captured."""
    report = model.get('report') if isinstance(model, dict) else None
    parts = report.get('parts') if isinstance(report, dict) else None
    if not isinstance(parts, list) or not parts:
        return None
    cleaned = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'fields':
            rows = [
                row for row in (part.get('rows') or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
                and str(row[1] if row[1] is not None else '').strip()
            ]
            if not rows:
                continue
            part = {**part, 'rows': rows}
        elif part.get('type') == 'table':
            headers = [str(header or '').strip() for header in (part.get('headers') or [])]
            kept_indexes = [index for index, header in enumerate(headers)
                            if header not in FINANCIAL_REPORT_DROP_COLUMNS]
            if not kept_indexes:
                continue
            rows = [
                [row[index] if index < len(row) else '' for index in kept_indexes]
                for row in (part.get('rows') or []) if isinstance(row, (list, tuple))
            ]
            part = {**part, 'headers': [headers[index] for index in kept_indexes], 'rows': rows}
        cleaned.append(part)
    result = []
    for index, part in enumerate(cleaned):
        if part.get('type') == 'heading':
            level = int(part.get('level') or 2)
            has_content = False
            for following in cleaned[index + 1:]:
                if following.get('type') == 'heading' and int(following.get('level') or 2) <= level:
                    break
                if following.get('type') != 'heading':
                    has_content = True
                    break
            if not has_content:
                continue
        result.append(part)
    return result or None


def _financial_screen_sections(parts):
    """Keep the screen's labels, values and order while normalizing numeric display."""
    sections = []
    body = []

    def flush():
        if body and any(not item.startswith(('<h2>', '<h3>')) for item in body):
            sections.append('<section>' + ''.join(body) + '</section>')
        body.clear()

    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get('type')
        if kind == 'heading':
            level = 3 if part.get('level') == 3 else 2
            if level == 2:
                flush()
            body.append(f'<h{level}>{_financial_report_escape(part.get("text"))}</h{level}>')
        elif kind == 'fields':
            rows = [
                row for row in (part.get('rows') or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
                and str(row[1] if row[1] is not None else '').strip()
            ]
            if not rows:
                continue
            regular_rows = [row for row in rows if str(row[0] or '').strip() != 'الإيضاحات']
            if regular_rows:
                body.append('<table class="summary-table"><tbody>' + ''.join(
                    f'<tr><th>{_financial_report_escape(row[0])}</th>'
                    + _financial_report_cell(_financial_report_format_display(row[1], row[0]), row[1]) + '</tr>'
                    for row in regular_rows) + '</tbody></table>')
            for row in rows:
                if str(row[0] or '').strip() == 'الإيضاحات':
                    body.append('<div class="financial-clarifications">'
                                + _financial_report_escape(row[1]) + '</div>')
        elif kind == 'table':
            headers = [header for header in (part.get('headers') or [])]
            if not headers:
                continue
            rows = [row for row in (part.get('rows') or []) if isinstance(row, (list, tuple))]
            if not rows:
                body.append('<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>')
                continue
            head = ''.join(f'<th>{_financial_report_escape(header)}</th>' for header in headers)
            cells = ''.join(
                '<tr>' + ''.join(
                    _financial_report_cell(
                        _financial_report_format_display(cell, headers[index] if index < len(headers) else ''),
                        cell,
                    )
                    for index, cell in enumerate(row)
                ) + '</tr>'
                for row in rows)
            wide = ' wide' if len(headers) > 8 else ''
            body.append(f'<table class="data-table{wide}"><thead><tr>{head}</tr></thead><tbody>{cells}</tbody></table>')
    flush()
    return sections


def build_financial_report_html(project_name, model, branding, tenant_id):
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    rental_on = mode in {'rental', 'mixed'}
    font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
    font_css = (font_css or '').replace('.slide', '.financial-report')
    rows = lambda keys: _financial_report_rows([(label, inputs.get(key), key) for key, label in keys])
    sections = []
    sections.append(f'<section class="cover"><div class="eyebrow">دراسة مالية</div><h1>{_financial_report_escape(project_name)}</h1><h2>التقرير المالي المنظم</h2><p>تم إنشاء التقرير من النسخة المعتمدة للمدخلات والافتراضات.</p></section>')
    screen_parts = _financial_screen_parts(model)
    if screen_parts:
        sections.extend(_financial_screen_sections(screen_parts))
        return _financial_report_document(sections, font_css, font_family)
    dev_duration_key = 'developmentDurationText' if inputs.get('developmentDurationText') else 'developmentYears'
    sections.append('<section><h2>1. ملخص المشروع</h2>' + rows([('unitRevenueMode', 'طبيعة الإيرادات'), (dev_duration_key, 'مدة التطوير'), ('operationYears', 'سنوات التشغيل'), ('landArea', 'مساحة الأرض')]) + '</section>')
    sections.append('<section><h2>2. الأرض والمساحات</h2>' + rows([('landArea', 'مساحة الأرض'), ('coverageRate', 'نسبة التغطية'), ('floorCount', 'عدد الطوابق'), ('builtUpAreaAbove', 'مسطحات البناء فوق الأرض'), ('basementArea', 'مساحة البدرومات'), ('landValueMethod', 'طريقة احتساب قيمة الأرض'), ('landStatus', 'حالة الأرض')]) + '</section>')
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'),
        ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'),
        ('7', 'المصروفات التشغيلية', 'opexTable'),
    ):
        sections.append(f'<section><h2>{number}. {title}</h2>{_financial_report_table(tables.get(table_key))}</section>')
    if inputs.get('developerPaymentsEnabled', 'yes') == 'yes':
        sections.insert(-1, f'<section><h2>6. مراحل التطوير ودفعات المطور</h2>{_financial_report_table(tables.get("scheduleTable"))}</section>')
    if rental_on and inputs.get('graceEnabled') == 'yes':
        grace_rows = [
            ('طريقة احتساب السماح', inputs.get('graceMethod'), 'graceMethod'),
            ('نطاق فترة السماح', inputs.get('graceScope'), 'graceScope'),
            ('سنة بداية السماح', inputs.get('graceStartYear'), 'graceStartYear'),
            ('مدة السماح (شهر)', inputs.get('graceDurationMonths'), 'graceDurationMonths'),
            ('نسبة الخصم %', inputs.get('graceDiscountRate'), 'graceDiscountRate'),
            ('إجمالي الخصم', inputs.get('graceTotalDiscount') or projection.get('totalGraceDiscount'), 'graceTotalDiscount'),
        ]
        grace_html = '<section><h2>فترة السماح للمستأجرين</h2>' + _financial_report_rows(grace_rows)
        if inputs.get('graceMethod') == 'schedule' and tables.get('graceScheduleTable'):
            grace_html += _financial_report_table(tables.get('graceScheduleTable'))
        grace_html += '</section>'
        sections.append(grace_html)
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        sections.append('<section><h2>8. الصندوق وأتعابه</h2>' + rows([('fundFeeBase', 'أساس الأتعاب'), ('fundCapitalInput', 'رأس مال الصندوق'), ('fundManagementRate', 'نسبة الإدارة'), ('fundFeeStartYear', 'بداية الاحتساب'), ('fundFeeEndYear', 'نهاية الاحتساب')]) + _financial_report_table(tables.get('fundAdditionalFeesTable')) + '</section>')
    if inputs.get('financeEnabled') == 'yes':
        murabaha_table_html = _financial_report_table(tables.get('financeMurabahaTable')) if tables.get('financeMurabahaTable') else ''
        sections.append('<section><h2>9. التمويل</h2>' + rows([('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'), ('annualFinanceRate', 'معدل المرابحة'), ('financeInterestMethod', 'طريقة المرابحة'), ('financeDrawYears', 'سنوات السحب'), ('financeRepaymentYears', 'سنوات السداد')]) + _financial_report_table(tables.get('financeDrawTable')) + _financial_report_table(tables.get('financeRepaymentTable')) + murabaha_table_html + '</section>')
    if inputs.get('externalEnabled') == 'yes' and tables.get('externalTable'):
        sections.append('<section><h2>10. البنود الخارجية</h2>' + _financial_report_table(tables.get('externalTable')) + '</section>')
    if inputs.get('exitEnabled') == 'yes':
        sections.append('<section><h2>11. التخارج</h2>' + rows([('saleExitMethod', 'التخارج البيعي'), ('saleExitYear', 'سنة التخارج البيعي'), ('exitMethod', 'التخارج التشغيلي'), ('operatingExitYear', 'سنة التخارج التشغيلي'), ('exitInput', 'مدخل التخارج')]) + '</section>')
    filtered_results = _filter_financial_results(inputs, projection)
    sections.append('<section class="keep-together"><h2>12. النتائج المالية</h2>' + _financial_report_rows(filtered_results) + '</section>')
    cf_rows = _filter_cashflow_columns(tables.get('cashflowTable'), inputs)
    sections.append('<section class="wide-table"><h2>13. التدفقات النقدية السنوية</h2>' + _financial_report_table(cf_rows) + '</section>')
    sensitivity_assumptions = tables.get('sensitivityAssumptionsTable')
    if not isinstance(sensitivity_assumptions, list) or not sensitivity_assumptions:
        dynamic_rows = model.get('dynamicRows') if isinstance(model, dict) else {}
        if isinstance(dynamic_rows, dict) and isinstance(dynamic_rows.get('sensitivity'), list):
            sensitivity_assumptions = dynamic_rows.get('sensitivity')
    sections.append(
        '<section class="wide-table"><h2>14. تحليل الحساسية العام</h2>'
        + '<h3>افتراضات السيناريوهات</h3>' + _financial_report_table(sensitivity_assumptions)
        + '<h3>النتائج المقارنة</h3>' + _financial_report_table(tables.get('sensitivityTable'))
        + '</section>'
    )
    clarifications = str(inputs.get('financialClarifications') or '').strip()
    if clarifications:
        sections.append('<section><h2>15. الإيضاحات</h2><div class="financial-clarifications">'
                        + _financial_report_escape(clarifications) + '</div></section>')
    return _financial_report_document(sections, font_css, font_family)


def _financial_report_document(sections, font_css, font_family):
    """One readable monochrome sheet.

    Branding colours used to paint this: a light `secondary_color` printed the label column of
    every summary table as pale text on a pale tint, which is unreadable. A financial table is
    read for its figures, so the report is deliberately black on white with grey chrome.
    """
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
{font_css}
@page {{ size: A4 landscape; margin: 10mm; }}
* {{ box-sizing:border-box; }} body {{ margin:0; color:#1a1a1a; background:#fff; font-family:{font_family}; direction:rtl; line-height:1.5; }}
.financial-report {{ max-width:none; margin:0; }} section {{ margin:0 0 16px; page-break-inside:auto; }}
.keep-together {{ break-inside:avoid; page-break-inside:avoid; }}
.wide-table table, table.wide {{ font-size:8px; }} .wide-table th,.wide-table td, table.wide th, table.wide td {{ padding:4px; white-space:normal; word-break:break-word; }}
.cover {{ min-height:175mm; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border:2px solid #1a1a1a; padding:30px; page-break-after:always; }}
.eyebrow {{ color:#4a4a4a; font-weight:700; }} h1 {{ color:#1a1a1a; font-size:32px; margin:18px 0 6px; }} h2 {{ color:#1a1a1a; font-size:20px; border-bottom:2px solid #1a1a1a; padding-bottom:6px; }}
h3 {{ color:#1a1a1a; font-size:14px; margin:12px 0 6px; }}
table {{ width:100%; border-collapse:collapse; margin:8px 0 14px; font-size:10px; }} th,td {{ border:1px solid #b3b3b3; padding:6px; text-align:right; vertical-align:top; color:#1a1a1a; }} thead {{ display:table-header-group; }} tr {{ break-inside:avoid; page-break-inside:avoid; }} thead th {{ background:#e6e6e6; font-weight:700; }} .summary-table th {{ width:38%; background:#f2f2f2; font-weight:400; }} .summary-table td {{ font-weight:700; }} .empty {{ color:#555; border:1px dashed #b3b3b3; padding:10px; }}
.financial-clarifications {{ white-space:pre-wrap; border:1px solid #b3b3b3; padding:10px; font-size:10px; line-height:1.6; }}
</style></head><body><main class="financial-report">{''.join(sections)}</main></body></html>'''


def _financial_pdf_text(value, key=''):
    raw = _financial_report_format_number(value, key)
    return html_lib.unescape(raw).replace('\xa0', ' ')


