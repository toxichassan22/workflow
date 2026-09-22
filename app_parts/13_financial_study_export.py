


def _financial_inputs(model):
    if not isinstance(model, dict):
        return {}
    inputs = model.get('inputs')
    return inputs if isinstance(inputs, dict) else model


def _financial_has_value(value):
    return value is not None and not (isinstance(value, str) and not value.strip())


def validate_financial_model(model):
    """Validate only fields activated by the financial model switches."""
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    errors = []

    def required(key, label=None):
        if not _financial_has_value(inputs.get(key)):
            errors.append({'field': key, 'message': f'{label or key} مطلوب عند تفعيل هذا الخيار'})

    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    if sales_on:
        required('salesStartYear', 'سنة بدء البيع')
        required('salesYears', 'عدد سنوات البيع')
    if rental_on:
        required('operationYears', 'عدد سنوات التشغيل')

    required('developmentYears', 'مدة التطوير')
    required('landArea', 'مساحة الأرض')
    required('builtUpAreaAbove', 'مسطحات البناء فوق الأرض')

    if inputs.get('financeEnabled') == 'yes':
        for key, label in (
            ('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'),
            ('financeArrangementFeeRate', 'رسوم ترتيب التمويل'),
            ('financeInterestMethod', 'طريقة احتساب الفائدة'), ('annualFinanceRate', 'معدل الفائدة'),
            ('financeDrawYears', 'سنوات سحب التمويل'),
            ('financeRepaymentStartYear', 'سنة بدء السداد'),
            ('financeRepaymentYears', 'سنوات السداد'),
        ):
            required(key, label)
        draw_rows = tables.get('financeDrawTable') or []
        repayment_rows = tables.get('financeRepaymentTable') or []
        if not draw_rows:
            errors.append({'field': 'financeDrawTable', 'message': 'خطة سحب التمويل مطلوبة عند تفعيل التمويل'})
        if not repayment_rows:
            errors.append({'field': 'financeRepaymentTable', 'message': 'خطة سداد التمويل مطلوبة عند تفعيل التمويل'})

    fund_on = inputs.get('fundEnabled') == 'yes'
    fees_on = fund_on and inputs.get('fundFeesEnabled') == 'yes'
    if fees_on:
        required('fundFeeBase', 'أساس أتعاب الصندوق')
        for key, label in (
            ('fundFeeStartYear', 'بداية احتساب أتعاب الصندوق'),
            ('fundFeeEndYear', 'نهاية احتساب أتعاب الصندوق'),
            ('fundFeeFrequency', 'دورية السداد'), ('fundFeeTiming', 'توقيت السداد'),
            ('fundFeeGrowthRate', 'نسبة نمو الأتعاب'),
        ):
            required(key, label)
        base = inputs.get('fundFeeBase')
        if base in {'fundCapital', 'investedCapital'}:
            required('fundCapitalInput', 'رأس مال الصندوق')
        elif base == 'nav':
            required('fundNavInput', 'صافي قيمة الأصول')
        elif base == 'fixed':
            required('fundFixedAnnualFee', 'الأتعاب السنوية الثابتة')

        if inputs.get('fundExitFeeEnabled') == 'yes':
            required('fundExitFeeBase', 'أساس أتعاب التخارج')
            if inputs.get('fundExitFeeBase') == 'fixed':
                required('fundExitFixedFee', 'مبلغ أتعاب التخارج')
            else:
                required('fundExitFeeRate', 'نسبة أتعاب التخارج')
        if inputs.get('performanceFeeEnabled') == 'yes':
            for key, label in (
                ('hurdleRate', 'الحد الأدنى للعائد'), ('hurdleMethod', 'طريقة الحد الأدنى'),
                ('performanceFeeRate', 'نسبة حافز الأداء'), ('performanceFeeBase', 'أساس حافز الأداء'),
                ('performanceCrystallizationYear', 'سنة احتساب حافز الأداء'),
            ):
                required(key, label)
            if inputs.get('catchupEnabled') == 'yes':
                required('catchupRate', 'نسبة Catch-up')
        additional_fees = tables.get('fundAdditionalFeesTable') or []
        for index, row in enumerate(additional_fees):
            if not isinstance(row, dict):
                continue
            if _financial_has_value(row.get('name')) and not _financial_has_value(row.get('value')):
                errors.append({'field': f'fundAdditionalFeesTable[{index}].value', 'message': 'قيمة الأتعاب الإضافية مطلوبة'})

    if rental_on and inputs.get('graceEnabled') == 'yes':
        for key, label in (
            ('graceMethod', 'طريقة فترة السماح'), ('graceScope', 'نطاق فترة السماح'),
            ('graceStartYear', 'سنة بداية السماح'), ('graceDurationMonths', 'مدة السماح'),
            ('graceDiscountRate', 'نسبة الخصم'),
        ):
            required(key, label)
        if inputs.get('graceScope') == 'selectedRevenue':
            required('graceRevenueId', 'الإيراد المشمول بالسماح')
        if inputs.get('graceMethod') == 'schedule' and not tables.get('graceScheduleTable'):
            errors.append({'field': 'graceScheduleTable', 'message': 'جدول خصومات فترة السماح مطلوب'})

    if inputs.get('externalEnabled') == 'yes' and not tables.get('externalTable'):
        errors.append({'field': 'externalTable', 'message': 'أضف بندًا خارجيًا واحدًا على الأقل'})

    if inputs.get('exitEnabled') == 'yes':
        if sales_on and inputs.get('saleExitMethod') not in (None, '', 'none'):
            required('saleExitYear', 'سنة التخارج البيعي')
        if rental_on and inputs.get('exitMethod') not in (None, '', 'none'):
            required('operatingExitYear', 'سنة التخارج التشغيلي')
            required('exitInput', 'مدخل التخارج التشغيلي')

    projection = model.get('projection') if isinstance(model, dict) else None
    if isinstance(projection, dict) and isinstance(projection.get('areaState'), dict) and projection['areaState'].get('valid') is False:
        errors.append({'field': 'componentsTable', 'message': 'مجموع مساحات مكونات المشروع يتجاوز مسطحات البناء فوق الأرض'})
    return errors


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
    'coverageRate', 'occupancy', 'costPct', 'devPct', 'drawPct', 'repaymentPct',
    'growth', 'occupancyReach', 'reachPct', 'financingRate', 'annualFinanceRate',
    'developerRate', 'financeArrangementFeeRate', 'fundManagementRate',
    'operatingExitCostRate', 'developerUpliftShare', 'roi', 'projectIrr', 'equityIrr',
}
_FINANCIAL_YEAR_KEYS = {
    'year', 'startYear', 'endYear', 'studyYear', 'operationYear', 'developmentYears',
    'operationYears', 'salesStartYear', 'salesYears', 'landContributionYear',
    'financeDrawYears', 'financeRepaymentStartYear', 'financeRepaymentYears',
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


def _financial_rounded_text(value, grouped=True):
    try:
        rounded = Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return ''
    if rounded == rounded.to_integral_value():
        return f'{int(rounded):,}' if grouped else str(int(rounded))
    return f'{rounded:,.1f}' if grouped else f'{rounded:.1f}'


def _financial_report_format_number(value, key=''):
    number = _financial_report_plain_number(value)
    if number is None:
        return _financial_report_escape(value)
    field = str(key or '')
    if field in _FINANCIAL_PERCENT_KEYS or (isinstance(value, str) and '%' in str(value)):
        if field in {'roi', 'projectIrr', 'equityIrr', 'irr'} and isinstance(value, (int, float)):
            display = number * 100
        elif field in {'occupancyReach'} and abs(number) <= 1:
            display = number * 100
        else:
            display = number
        return html_lib.escape(_financial_rounded_text(display, grouped=False) + '%')
    if field in {'payback', 'equityPayback'} or (isinstance(value, str) and 'سنة' in str(value)):
        return html_lib.escape(_financial_rounded_text(number, grouped=False) + ' سنة')
    if field in _FINANCIAL_YEAR_KEYS and float(number).is_integer() and abs(number) < 10000:
        return html_lib.escape(str(int(number)))
    return html_lib.escape(_financial_rounded_text(number))


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
        formatted = _financial_rounded_text(number, grouped=not (percent or year))
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
        return _financial_rounded_text(number, grouped=not trailing.startswith(('%', '٪')))

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
    ('totalFinanceInterest', 'إجمالي فوائد التمويل'),
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
        drop_columns.update({'financeDraw', 'سحب التمويل', 'financeInterest', 'فائدة التمويل', 'financeFee', 'رسوم التمويل', 'financeRepayment', 'سداد أصل التمويل', 'openingDebt', 'closingDebt', 'فائدة ورسوم التمويل'})
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
    'drawPct': 'نسبة السحب %', 'repaymentPct': 'نسبة السداد %',
    'value': 'المبلغ / النسبة', 'startYear': 'سنة البداية', 'endYear': 'سنة النهاية',
    'recurrence': 'التكرار', 'type': 'نوع البند', 'base': 'القيمة الأساسية', 'growth': 'النمو %',
    'amount': 'القيمة', 'phase': 'المرحلة', 'occupancyReach': 'الوصول للإشغال %',
    'saleRevenue': 'المبيعات', 'operatingRevenue': 'إيرادات التأجير',
    'noi': 'NOI',
    'graceDiscount': 'خصم فترة السماح', 'developmentCost': 'تكلفة التطوير',
    'developerPayment': 'دفعة المطور', 'opex': 'المصروفات', 'landRent': 'إيجار الأرض',
    'fundFeesAnnual': 'أتعاب الصندوق', 'financeDraw': 'سحب التمويل',
    'financeInterest': 'فائدة التمويل', 'financeFee': 'رسوم التمويل',
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
    'projected', 'cashflows', 'projectCashflows', 'financePlan', 'financeRepaymentPlan',
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
    sections.append('<section><h2>1. ملخص المشروع</h2>' + rows([('unitRevenueMode', 'طبيعة الإيرادات'), ('developmentYears', 'مدة التطوير'), ('operationYears', 'سنوات التشغيل'), ('landArea', 'مساحة الأرض')]) + '</section>')
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
    if inputs.get('financeEnabled') == 'yes':
        sections.append('<section><h2>8. التمويل</h2>' + rows([('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'), ('annualFinanceRate', 'معدل الفائدة'), ('financeInterestMethod', 'طريقة الفائدة'), ('financeDrawYears', 'سنوات السحب'), ('financeRepaymentYears', 'سنوات السداد')]) + _financial_report_table(tables.get('financeDrawTable')) + _financial_report_table(tables.get('financeRepaymentTable')) + '</section>')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        sections.append('<section><h2>9. الصندوق وأتعابه</h2>' + rows([('fundFeeBase', 'أساس الأتعاب'), ('fundCapitalInput', 'رأس مال الصندوق'), ('fundManagementRate', 'نسبة الإدارة'), ('fundFeeStartYear', 'بداية الاحتساب'), ('fundFeeEndYear', 'نهاية الاحتساب')]) + _financial_report_table(tables.get('fundAdditionalFeesTable')) + '</section>')
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


def _financial_pdf_plain_html(html):
    """Drop huge embedded fonts so the PyMuPDF HTML parser can open the report."""
    text = str(html or '')
    text = re.sub(r'@font-face\s*\{.*?\}', '', text, flags=re.S)
    text = re.sub(r'src:\s*url\(data:font/[^)]+\);?', '', text, flags=re.I)
    text = re.sub(r'<style>.*?</style>', '<style>body{font-family:Tahoma,Arial,sans-serif;direction:rtl}table{width:100%;border-collapse:collapse;font-size:10px}th,td{border:1px solid #ccc;padding:4px;text-align:right}h1,h2,h3{color:#123B6D}</style>', text, flags=re.S)
    return text


def _financial_pdf_font():
    return maps_service.bundled_arabic_font_path()


def _financial_pdf_shape(text):
    """PyMuPDF places glyphs verbatim, so Arabic must be shaped and ordered first."""
    value = str(text or '')
    if not re.search(r'[\u0600-\u06ff]', value):
        return value
    return maps_service.shape_arabic_for_drawing(value)


def _financial_pdf_has_text(output_path, minimum=200):
    """A PDF of table borders with no glyphs is a failed render, not a report.

    The MuPDF HTML engine writes exactly that on hosts with no system Arabic font,
    and the old size-only check accepted it, so the client downloaded blank pages.
    """
    import fitz
    try:
        document = fitz.open(output_path)
    except Exception as error:
        print(f'[FINANCIAL PDF] cannot inspect the written file ({error})')
        return False
    try:
        return sum(len(page.get_text().strip()) for page in document) >= minimum
    finally:
        document.close()


def _financial_pdf_text(value, key=''):
    raw = _financial_report_format_number(value, key)
    return html_lib.unescape(raw).replace('\xa0', ' ')


def generate_financial_pdf_from_model(project_name, model, output_path):
    import fitz
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    rental_on = mode in {'rental', 'mixed'}
    font_path = _financial_pdf_font()
    document = fitz.open()
    page_size = fitz.paper_rect('a4-l')
    page = document.new_page(width=page_size.width, height=page_size.height)
    margin = 28
    y = margin
    font_name = 'helv'
    if font_path:
        try:
            page.insert_font(fontname='arabic', fontfile=font_path)
            font_name = 'arabic'
        except Exception as error:
            print(f'[FINANCIAL PDF] custom font skipped ({error})')
            font_path = None
    metrics = fitz.Font(fontfile=font_path) if font_path else fitz.Font('helv')
    latin_metrics = fitz.Font('helv')

    def ensure_space(needed=24):
        nonlocal page, y
        if y + needed < page_size.height - margin:
            return
        page = document.new_page(width=page_size.width, height=page_size.height)
        if font_path:
            try:
                page.insert_font(fontname='arabic', fontfile=font_path)
            except Exception:
                pass
        y = margin

    def split_runs(value):
        """Group a visual-order line by which embedded font actually owns each glyph.

        The bundled Arabic font carries no Latin or percent glyph, so a single-font
        line drops them to empty boxes.
        """
        runs = []
        for character in value:
            arabic = font_name == 'arabic' and metrics.has_glyph(ord(character))
            name, font = (font_name, metrics) if arabic else ('helv', latin_metrics)
            if runs and runs[-1][0] == name:
                runs[-1][2] += character
            else:
                runs.append([name, font, character])
        return runs

    def place(rect, text, size, color=(0.15, 0.15, 0.15)):
        """Right-align one line with insert_text.

        insert_textbox silently draws nothing when its line height does not fit the
        rectangle, which is why the whole report used to come out as empty borders.
        """
        value = _financial_pdf_shape(text)
        if not value.strip():
            return
        runs = split_runs(value)
        width = lambda items: sum(font.text_length(part, size) for _, font, part in items)
        while len(value) > 1 and width(runs) > rect.width:
            value = value[1:]
            runs = split_runs(value)
        baseline = min(rect.y0 + size, rect.y1 - 1) if rect.height > size else rect.y0 + size
        x = max(rect.x0, rect.x1 - width(runs))
        for name, font, part in runs:
            page.insert_text((x, baseline), part, fontname=name, fontsize=size, color=color)
            x += font.text_length(part, size)

    def place_wrapped(rect, text, size, color=(0.1, 0.1, 0.1), max_lines=2):
        """Header cells carry whole Arabic phrases, so a single truncated line loses the column."""
        words = str(text or '').split(' ')
        lines, current = [], ''
        for word in words:
            candidate = (current + ' ' + word).strip()
            if current and metrics.text_length(_financial_pdf_shape(candidate), size) > rect.width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:max_lines]):
            top = rect.y0 + index * (size + 1)
            place(fitz.Rect(rect.x0, top, rect.x1, top + size + 1), line, size, color=color)

    def draw_text(text, size=11, indent=0):
        nonlocal y
        ensure_space(size + 8)
        box = fitz.Rect(margin + indent, y, page_size.width - margin, y + size + 6)
        place(box, text, size, color=(0.1, 0.1, 0.1))
        y += size + 8

    def draw_paragraph(text, size=9):
        nonlocal y
        width = page_size.width - margin * 2
        for paragraph in str(text or '').splitlines() or ['']:
            words = paragraph.split()
            if not words:
                y += size + 4
                continue
            line = ''
            for word in words:
                candidate = (line + ' ' + word).strip()
                shaped = _financial_pdf_shape(candidate)
                measured = sum(font.text_length(part, size) for _, font, part in split_runs(shaped))
                if line and measured > width:
                    draw_text(line, size)
                    line = word
                else:
                    line = candidate
            if line:
                draw_text(line, size)

    def draw_kv_table(rows, raw=False):
        nonlocal y
        visible = []
        for item in rows:
            label, value, key = (item + ('',))[:3] if len(item) < 3 else item
            if value in (None, '', [], {}) or isinstance(value, (dict, list)):
                continue
            visible.append((
                str(label),
                html_lib.unescape(_financial_report_format_display(value, label)) if raw
                else _financial_pdf_text(value, key),
            ))
        if not visible:
            draw_text('لا توجد قيم مطبقة في هذا القسم.', 9)
            return
        col_w = (page_size.width - margin * 2) / 2
        for label, value in visible:
            if label.strip() == 'الإيضاحات':
                draw_paragraph(value)
                y += 4
                continue
            ensure_space(16)
            rect = fitz.Rect(margin, y, page_size.width - margin, y + 15)
            page.draw_rect(rect, color=(0.85, 0.82, 0.8), width=0.4)
            place(fitz.Rect(rect.x0 + col_w + 4, rect.y0 + 2, rect.x1 - 4, rect.y1), label, 8)
            place(fitz.Rect(rect.x0 + 4, rect.y0 + 2, rect.x0 + col_w - 4, rect.y1), value, 8)
            y += 15

    def draw_data_table(rows, title):
        nonlocal y
        if not isinstance(rows, list) or not rows:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        keys = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                label = FINANCIAL_COLUMN_LABELS.get(key, key)
                if key in FINANCIAL_REPORT_DROP_COLUMNS or label in FINANCIAL_REPORT_DROP_COLUMNS:
                    continue
                if key not in keys:
                    keys.append(key)
        if not keys:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        preferred = {
            'cashflowTable': ['year', 'phase', 'saleRevenue', 'operatingRevenue', 'developmentCost', 'developerPayment', 'opex', 'noi', 'financeDraw', 'financeInterest', 'final', 'cumulative'],
            'sensitivityAssumptionsTable': ['key', 'low', 'high'],
            'sensitivityTable': ['scenario', 'totalRevenue', 'investmentCost', 'netProfit', 'roi', 'projectIrr', 'equityRequired'],
        }
        wanted = preferred.get(title) or preferred.get(next((key for key in ('cashflowTable', 'sensitivityAssumptionsTable', 'sensitivityTable') if key in title), ''))
        if 'التدفقات' in title:
            wanted = preferred['cashflowTable']
        elif 'الافتراضات' in title:
            wanted = preferred['sensitivityAssumptionsTable']
        elif 'النتائج' in title and 'حساسية' in title:
            wanted = preferred['sensitivityTable']
        if wanted:
            keys = [key for key in wanted if key in keys] or keys[:8]
        elif len(keys) > 8:
            keys = keys[:8]
        draw_text(title, 12)
        usable = page_size.width - margin * 2
        col_w = usable / max(1, len(keys))
        row_h = 14
        def paint_row(values, header=False):
            nonlocal y
            ensure_space(row_h)
            x = margin
            for value in reversed(values):
                cell = fitz.Rect(x, y, x + col_w, y + row_h)
                fill = (0.07, 0.23, 0.43) if header else None
                page.draw_rect(cell, color=(0.85, 0.82, 0.8), fill=fill, width=0.4)
                color = (1, 1, 1) if header else (0.15, 0.15, 0.15)
                place(cell + (2, 1, -2, -1), value, 7, color=color)
                x += col_w
            y += row_h
        paint_row([FINANCIAL_COLUMN_LABELS.get(key, key) for key in keys], header=True)
        for row in rows:
            if isinstance(row, dict):
                paint_row([_financial_pdf_text(row.get(key), key) for key in keys])

    def draw_grid(headers, rows):
        """Draw a screen table verbatim. Columns beyond a readable page width continue in a
        second band that repeats the first column, so no entered figure is dropped."""
        nonlocal y
        if not headers:
            return
        if not rows:
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        rows = [
            [
                html_lib.unescape(_financial_report_format_display(
                    value, headers[index] if index < len(headers) else ''
                ))
                for index, value in enumerate(row)
            ]
            for row in rows
        ]
        cell = lambda row, index: str(row[index]).strip() if index < len(row) else ''
        max_columns = 9
        bands = [(headers, rows)]
        if len(headers) > max_columns:
            bands = []
            for start in range(1, len(headers), max_columns - 1):
                picked = list(range(start, min(start + max_columns - 1, len(headers))))
                bands.append(([headers[0]] + [headers[index] for index in picked],
                              [[cell(row, 0)] + [cell(row, index) for index in picked] for row in rows]))
        for band_headers, band_rows in bands:
            col_w = (page_size.width - margin * 2) / len(band_headers)
            ensure_space(38)
            top = y
            x = margin
            for header in reversed(band_headers):
                box = fitz.Rect(x, top, x + col_w, top + 22)
                page.draw_rect(box, color=(0.7, 0.7, 0.7), fill=(0.9, 0.9, 0.9), width=0.4)
                place_wrapped(box + (2, 2, -2, -2), header, 7)
                x += col_w
            y = top + 22
            for row in band_rows:
                ensure_space(14)
                top = y
                x = margin
                for index in reversed(range(len(band_headers))):
                    box = fitz.Rect(x, top, x + col_w, top + 14)
                    page.draw_rect(box, color=(0.7, 0.7, 0.7), width=0.4)
                    place(box + (2, 1, -2, -1), cell(row, index), 7)
                    x += col_w
                y = top + 14
            y += 8

    screen_parts = _financial_screen_parts(model)
    if screen_parts:
        draw_text(project_name or 'الدراسة المالية', 18)
        for part in screen_parts:
            if not isinstance(part, dict):
                continue
            kind = part.get('type')
            if kind == 'heading':
                draw_text(str(part.get('text') or ''), 10 if part.get('level') == 3 else 12)
            elif kind == 'fields':
                draw_kv_table([(row[0], row[1], '') for row in (part.get('rows') or [])
                               if isinstance(row, (list, tuple)) and len(row) >= 2], raw=True)
            elif kind == 'table':
                draw_grid([str(header) for header in (part.get('headers') or [])],
                          [list(row) for row in (part.get('rows') or []) if isinstance(row, (list, tuple))])
        document.save(output_path)
        document.close()
        return output_path

    draw_text(project_name or 'الدراسة المالية', 18)
    draw_text('التقرير المالي المنظم', 13)
    draw_text('1. ملخص المشروع', 12)
    draw_kv_table([
        ('طبيعة الإيرادات', inputs.get('unitRevenueMode'), 'unitRevenueMode'),
        ('مدة التطوير', inputs.get('developmentYears'), 'developmentYears'),
        ('سنوات التشغيل', inputs.get('operationYears'), 'operationYears'),
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
    ])
    draw_text('2. الأرض والمساحات', 12)
    draw_kv_table([
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
        ('نسبة التغطية', inputs.get('coverageRate'), 'coverageRate'),
        ('عدد الطوابق', inputs.get('floorCount'), 'floorCount'),
        ('مسطحات البناء فوق الأرض', inputs.get('builtUpAreaAbove'), 'builtUpAreaAbove'),
        ('مساحة البدرومات', inputs.get('basementArea'), 'basementArea'),
        ('حالة الأرض', inputs.get('landStatus'), 'landStatus'),
    ])
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'),
        ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'),
    ):
        draw_data_table(tables.get(table_key), f'{number}. {title}')
    if inputs.get('developerPaymentsEnabled', 'yes') == 'yes':
        draw_data_table(tables.get('scheduleTable'), '6. مراحل التطوير ودفعات المطور')
    draw_data_table(tables.get('opexTable'), '7. المصروفات التشغيلية')
    if rental_on and inputs.get('graceEnabled') == 'yes':
        draw_text('فترة السماح للمستأجرين', 12)
        draw_kv_table([
            ('طريقة احتساب السماح', inputs.get('graceMethod'), 'graceMethod'),
            ('نطاق فترة السماح', inputs.get('graceScope'), 'graceScope'),
            ('سنة بداية السماح', inputs.get('graceStartYear'), 'graceStartYear'),
            ('مدة السماح (شهر)', inputs.get('graceDurationMonths'), 'graceDurationMonths'),
            ('نسبة الخصم %', inputs.get('graceDiscountRate'), 'graceDiscountRate'),
            ('إجمالي الخصم', inputs.get('graceTotalDiscount') or projection.get('totalGraceDiscount'), 'graceTotalDiscount'),
        ])
        if inputs.get('graceMethod') == 'schedule' and tables.get('graceScheduleTable'):
            draw_data_table(tables.get('graceScheduleTable'), 'جدول خصومات فترة السماح')
    if inputs.get('financeEnabled') == 'yes':
        draw_text('8. التمويل', 12)
        draw_kv_table([
            ('أساس التمويل', inputs.get('financeBase'), 'financeBase'),
            ('نسبة التمويل', inputs.get('financingRate'), 'financingRate'),
            ('معدل الفائدة', inputs.get('annualFinanceRate'), 'annualFinanceRate'),
            ('قيمة أساس التمويل', inputs.get('financeBaseAmount') or projection.get('financeBaseAmount'), 'financeBaseAmount'),
            ('قيمة التسهيل التمويلي', inputs.get('facilityAmount') or projection.get('facilityAmount'), 'facilityAmount'),
        ])
        draw_data_table(tables.get('financeDrawTable'), 'خطة السحب')
        draw_data_table(tables.get('financeRepaymentTable'), 'خطة السداد')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        draw_text('9. الصندوق وأتعابه', 12)
        draw_kv_table([
            ('أساس الأتعاب', inputs.get('fundFeeBase'), 'fundFeeBase'),
            ('نسبة الإدارة', inputs.get('fundManagementRate'), 'fundManagementRate'),
        ])
        draw_data_table(tables.get('fundAdditionalFeesTable'), 'أتعاب إضافية')
    if inputs.get('externalEnabled') == 'yes' and tables.get('externalTable'):
        draw_text('10. البنود الخارجية', 12)
        draw_data_table(tables.get('externalTable'), 'البنود الخارجية')
    if inputs.get('exitEnabled') == 'yes':
        draw_text('11. التخارج', 12)
        draw_kv_table([
            ('التخارج البيعي', inputs.get('saleExitMethod'), 'saleExitMethod'),
            ('التخارج التشغيلي', inputs.get('exitMethod'), 'exitMethod'),
            ('سنة التخارج التشغيلي', inputs.get('operatingExitYear'), 'operatingExitYear'),
        ])
    draw_text('12. النتائج المالية', 12)
    filtered_results = _filter_financial_results(inputs, projection)
    draw_kv_table(filtered_results)
    cf_rows = _filter_cashflow_columns(tables.get('cashflowTable'), inputs)
    draw_data_table(cf_rows, '13. التدفقات النقدية السنوية')
    sensitivity_assumptions = tables.get('sensitivityAssumptionsTable')
    if not isinstance(sensitivity_assumptions, list) or not sensitivity_assumptions:
        dynamic_rows = model.get('dynamicRows') if isinstance(model, dict) else {}
        if isinstance(dynamic_rows, dict) and isinstance(dynamic_rows.get('sensitivity'), list):
            sensitivity_assumptions = dynamic_rows.get('sensitivity')
    draw_data_table(sensitivity_assumptions, '14. تحليل الحساسية العام - الافتراضات')
    draw_data_table(tables.get('sensitivityTable'), '14. تحليل الحساسية العام - النتائج')
    clarifications = str(inputs.get('financialClarifications') or '').strip()
    if clarifications:
        draw_text('15. الإيضاحات', 12)
        draw_paragraph(clarifications)
    document.save(output_path)
    document.close()
    return output_path


def generate_financial_pdf(html, output_path, model=None, project_name='', min_text=200):
    last_error = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            try:
                page = browser.new_page()
                page.set_content(html, wait_until='load', timeout=45000)
                try:
                    page.evaluate('() => document.fonts && document.fonts.ready')
                except Exception:
                    pass
                page.pdf(
                    path=str(output_path),
                    format='A4',
                    landscape=True,
                    print_background=True,
                    margin={'top': '12mm', 'right': '12mm', 'bottom': '12mm', 'left': '12mm'},
                )
            finally:
                browser.close()
        if os.path.isfile(output_path) and _financial_pdf_has_text(output_path, min_text):
            return output_path
        last_error = RuntimeError('Playwright wrote an empty PDF')
    except Exception as error:
        last_error = error
        print(f'[FINANCIAL PDF] Playwright failed ({error}); falling back to PyMuPDF')
    # The model writer embeds the Arabic font itself, so it is the reliable engine on
    # hosts without Chromium. The MuPDF HTML engine relies on system fonts and writes
    # pages of empty table borders there, so it is only the last resort.
    if model is not None:
        try:
            generate_financial_pdf_from_model(project_name, model, output_path)
            if _financial_pdf_has_text(output_path, min_text):
                return output_path
            last_error = RuntimeError('Model renderer wrote a PDF with no text')
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] model fallback failed ({error})')
    import fitz
    candidates = [_financial_pdf_plain_html(html), str(html or '')]
    for candidate in candidates:
        try:
            document = fitz.open('html', candidate.encode('utf-8'))
            try:
                document.save(output_path)
            finally:
                document.close()
            if os.path.isfile(output_path) and _financial_pdf_has_text(output_path, min_text):
                return output_path
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] PyMuPDF html open failed ({error})')
    raise RuntimeError(str(last_error or 'Could not write financial PDF'))


@app.route('/api/financial-study/validate', methods=['POST'])
@require_permission('create_presentation')
def api_validate_financial_study():
    data = request.json or {}
    errors = validate_financial_model(data.get('financialModel') or data.get('model') or {})
    return jsonify({'success': not errors, 'validation': errors})


@app.route('/api/financial-study/export', methods=['POST'])
@require_auth
def api_export_financial_study():
    data = request.json or {}
    model = data.get('financialModel') or data.get('model') or {}
    errors = validate_financial_model(model)
    if errors:
        return jsonify({'success': False, 'error': 'لا يمكن تصدير الدراسة قبل استكمال المدخلات المطلوبة', 'validation': errors}), 400
    project_name = str(data.get('projectName') or 'الدراسة المالية').strip()[:120] or 'الدراسة المالية'
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)
    safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'financial-study'
    output_path = os.path.join(tenant_output_dir, f'{safe_name}_{int(time.time())}_financial.pdf')
    try:
        branding = db.get_branding(g.tenant_id) or {}
        report_html = build_financial_report_html(project_name, model, branding, g.tenant_id)
        generate_financial_pdf(report_html, output_path, model=model, project_name=project_name)
        export_id = db.create_export(data.get('presentationId') or None, g.tenant_id, 'financial_pdf', output_path)
        return jsonify({
            'success': True,
            'exportId': export_id,
            'format': 'financial_pdf',
            'fileName': os.path.basename(output_path),
            'url': f'/api/exports/{export_id}/download',
        })
    except Exception as error:
        print(f'[FINANCIAL PDF ERROR] {type(error).__name__}: {error!r}')
        if os.path.exists(output_path):
            os.unlink(output_path)
        detail = str(error).strip() or type(error).__name__
        return jsonify({'success': False, 'error': 'تعذر إنشاء ملف الدراسة المالية: ' + detail}), 500


def _export_html_from_slides(slides_data):
    """Join the deck for export, making sure every entry contributes exactly one page.

    Joining the stored html and hoping for the best is how a 50-slide deck exported as 25 pages
    with nothing to point at. Each entry is inspected on its own: an entry whose html carries no
    root `.slide` element is wrapped in one (it would otherwise print as loose content sharing a
    neighbour's page), and an entry carrying several is reported. The notes are logged and returned
    with the error, so the failure names the slide instead of only counting.
    """
    from design_templates import extract_slide_elements

    pieces = []
    empty = []
    wrapped = []
    multiple = []
    for index, item in enumerate(slides_data if isinstance(slides_data, list) else [], 1):
        html = str((item or {}).get('html') or '').strip() if isinstance(item, dict) else str(item or '').strip()
        title = str((item or {}).get('title') or '').strip() if isinstance(item, dict) else ''
        if not html:
            empty.append(index)
            continue
        roots = extract_slide_elements(html)
        if len(roots) == 1:
            pieces.append(roots[0])
        elif len(roots) > 1:
            multiple.append(index)
            pieces.extend(roots)
        else:
            wrapped.append(index)
            pieces.append(
                '<div class="slide" style="width:1280px;height:720px;position:relative;'
                'overflow:hidden;background:#fff;">' + html + '</div>'
            )
        if not html.strip():
            print(f'[EXPORT] slide {index} ({title}) has no html')

    notes = []
    if empty:
        notes.append('شرائح بلا محتوى: ' + '، '.join(str(n) for n in empty))
    if wrapped:
        notes.append('شرائح بلا إطار شريحة (أُضيف لها إطار): ' + '، '.join(str(n) for n in wrapped))
    if multiple:
        notes.append('شرائح تحتوي أكثر من شريحة: ' + '، '.join(str(n) for n in multiple))
    print(f'[EXPORT] entries={len(slides_data or [])} printable={len(pieces)}')
    return '\n'.join(pieces), notes


@app.route('/api/export', methods=['POST'])
@require_permission('export_files')
def api_export():
    """
    Export presentation to PDF or PPTX.
    Input: {format: 'pdf'|'pptx', slidesHtml: '...', slidesData: [...], projectName: '...'}
    """
    data = request.json or {}
    # Safety net: if __chunked_body reached route handler, perform inline reassembly
    if '__chunked_body' in data and isinstance(data.get('__chunked_body'), dict):
        meta = data['__chunked_body']
        fallback_id = str(meta.get('id', ''))
        fallback_total = meta.get('total')
        fallback_gzip = bool(meta.get('gzip'))
        chunk_dir = _body_chunk_dir(fallback_id)
        if chunk_dir and os.path.isdir(chunk_dir) and isinstance(fallback_total, int) and (1 <= fallback_total <= 1024):
            try:
                parts = []
                for i in range(fallback_total):
                    with open(os.path.join(chunk_dir, f'{i}.part'), 'rb') as part_fh:
                        parts.append(part_fh.read())
                raw = b''.join(parts)
                if fallback_gzip:
                    import gzip as _gzip
                    raw = _gzip.decompress(raw)
                data = json.loads(raw.decode('utf-8'))
                import shutil as _shutil
                _shutil.rmtree(chunk_dir, ignore_errors=True)
                print(f"[EXPORT] Inline chunked body reassembly succeeded for {fallback_id}")
            except Exception as _fb_err:
                print(f"[EXPORT] Inline chunked body reassembly failed: {_fb_err}")
    fmt = data.get('format', 'pdf').lower()
    project_name = data.get('projectName', 'presentation')
    export_notes = []
    branding = db.get_branding(g.tenant_id)
    print(f"[EXPORT] format={fmt} tenant={g.tenant_id} font_family={branding.get('font_family')!r} font_file_path={branding.get('font_file_path')!r}")

    # Tenant-specific output directory
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)

    try:
        if fmt == 'pdf':
            from exports.pdf_export import generate_pdf
            slides_html = data.get('slidesHtml', '')
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not _presentation_in_scope(pres):
                return jsonify({'error': 'Presentation not found'}), 404
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}
            render_project_data = copy.deepcopy(project_data)
            _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)

            # Fallback: load latest saved slides from DB
            if not slides_html and not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data: {e}")

            if slides_data:
                slides_data = slide_engine.renumber_presentation_slides(
                    slides_data, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
                    creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
                )
                slides_html, export_notes = _export_html_from_slides(slides_data)
                if export_notes:
                    print('[EXPORT] ' + ' | '.join(export_notes))
            if not slides_html:
                return jsonify({'error': 'slidesHtml or slidesData is required for PDF export'}), 400

            safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
            pdf_path = os.path.join(tenant_output_dir, f"{safe_name}_{int(time.time())}.pdf")
            # The deck's own count, so a file that came out short is visible here too. This used to
            # log len(slides_html) — the character count — as the number of slides.
            slide_count = len(slides_data) if slides_data else slides_html.count('class="slide"')
            generate_pdf(slides_html, branding, pdf_path, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pdf_path)}'
            # Which renderer wrote the file: 'chromium' / 'chromium-isolated' is the
            # faithful export, 'fitz-fallback' keeps the page count but shifts the
            # layout (white strip left, clipped right) when no browser runs on host.
            try:
                import generate_pdf_from_preview as _deck_renderer
                pdf_engine = getattr(_deck_renderer, 'LAST_PDF_ENGINE', '') or 'unknown'
            except Exception:
                pdf_engine = 'unknown'
            print(f'[EXPORT] engine={pdf_engine} pages={slide_count} file={os.path.basename(pdf_path)}')

            # Record export — d03: each produced file carries the content hash
            # it was rendered from, its regen policy and the billed run cost.
            export_content_hash = db._presentation_review_hash({
                'slides_data': slides_data if slides_data else slides_html,
                'project_data': project_data,
            })
            regen_policy, export_cost = _export_regen_policy(
                g.tenant_id, presentation_id, export_content_hash)
            export_id = db.create_export(
                presentation_id, g.tenant_id, 'pdf', pdf_path,
                content_hash=export_content_hash, cost_usd=export_cost,
                regen_policy=regen_policy)
            official = _export_is_official_row({
                'id': export_id, 'presentation_id': presentation_id,
                'content_hash': export_content_hash, 'file_path': pdf_path})
            if presentation_id:
                _record_change('presentation', presentation_id, 'تصدير',
                               [f'صُدّر العرض بصيغة PDF ({slide_count} شريحة)'])
            download_url = f'/api/exports/{export_id}/download' + ('' if official else '?draft=1')
            return jsonify({'success': True, 'url': download_url, 'exportId': export_id,
                            'format': 'pdf', 'engine': pdf_engine, 'officiallyApproved': official})

        elif fmt == 'pptx':
            from exports.pptx_export import generate_pptx
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not _presentation_in_scope(pres):
                return jsonify({'error': 'Presentation not found'}), 404
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}

            # Fallback: load latest saved slides from DB
            if not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data for PPTX: {e}")

            if not slides_data:
                return jsonify({'error': 'slidesData is required for PPTX export'}), 400
            slides_data = slide_engine.renumber_presentation_slides(
                slides_data, branding=branding, project_data=project_data, tenant_id=g.tenant_id,
                creative_images=_presentation_creative_images(project_data, g.tenant_id),
            )

            pptx_path = generate_pptx(slides_data, project_name, branding, tenant_output_dir, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pptx_path)}'
            # Native python-pptx build: no browser involved, and generate_pptx
            # already refused a short file. The count travels with the response
            # the same way the PDF engine does.
            pptx_count = len(slides_data)
            print(f'[EXPORT] engine=pptx-native slides={pptx_count} file={os.path.basename(pptx_path)}')

            pptx_hash = db._presentation_review_hash({
                'slides_data': slides_data, 'project_data': project_data})
            regen_policy, export_cost = _export_regen_policy(
                g.tenant_id, data.get('presentationId'), pptx_hash)
            export_id = db.create_export(
                data.get('presentationId'), g.tenant_id, 'pptx', pptx_path,
                content_hash=pptx_hash, cost_usd=export_cost, regen_policy=regen_policy)
            official = _export_is_official_row({
                'id': export_id, 'presentation_id': data.get('presentationId'),
                'content_hash': pptx_hash, 'file_path': pptx_path})
            if data.get('presentationId'):
                _record_change('presentation', data['presentationId'], 'تصدير',
                               [f'صُدّر العرض بصيغة PPTX ({len(slides_data)} شريحة)'])
            download_url = f'/api/exports/{export_id}/download' + ('' if official else '?draft=1')
            return jsonify({'success': True, 'url': download_url, 'exportId': export_id,
                            'format': 'pptx', 'engine': 'pptx-native', 'slideCount': pptx_count,
                            'officiallyApproved': official})

        else:
            return jsonify({'error': f'Unsupported format: {fmt}. Use pdf or pptx'}), 400

    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        # The notes name which slides the deck could not print, so the failure is actionable
        # instead of being a page count the user cannot act on.
        message = str(e)
        if export_notes:
            message += ' — ' + '؛ '.join(export_notes)
        return jsonify({'error': message, 'notes': export_notes}), 500


@app.route('/api/exports', methods=['GET'])
@require_auth
def api_get_exports():
    """List all exports for the current tenant."""
    exports = db.get_exports(
        g.tenant_id, accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    result = []
    for e in exports:
        result.append({
            'id': e['id'],
            'format': e['format'],
            'downloadUrl': f"/api/exports/{e['id']}/download",
            'createdAt': e.get('created_at'),
        })
    return jsonify({'success': True, 'exports': result})


def _export_content_cost(tenant_id, presentation_id):
    """The billed cost of the run that produced this presentation (d03)."""
    if not presentation_id:
        return 0.0
    try:
        row = db.get_db().execute(
            "SELECT amount_usd FROM tenant_ledger WHERE tenant_id = ? AND presentation_id = ? "
            "AND kind = 'debit' ORDER BY created_at DESC LIMIT 1",
            (tenant_id, presentation_id)).fetchone()
        return float(row['amount_usd']) if row else 0.0
    except Exception:
        return 0.0


def _export_regen_policy(tenant_id, presentation_id, content_hash):
    """d03: which content version an export carries, with the run's cost.

    'official' — the exported content is exactly what the final gate approved;
    'superseded' — the content drifted past the approved version and needs a
    new gate; 'draft' — the file never reached the final gate.
    """
    if not presentation_id:
        return 'draft', 0.0
    approval = db.latest_final_file_approval(tenant_id, presentation_id, status='approved')
    policy = 'draft'
    if approval and approval.get('request_hash'):
        policy = 'official' if approval['request_hash'] == content_hash else 'superseded'
    return policy, _export_content_cost(tenant_id, presentation_id)


def _export_is_official_row(export_row):
    """True when this export carries exactly the content the final gate approved.

    Three proofs, strongest first: the export's content hash matches the hash
    the approver reviewed; the export row is the one the stamp pinned; or the
    physical file still matches the stamped sha256.
    """
    presentation_id = export_row.get('presentation_id')
    if not presentation_id:
        return False
    approval = db.latest_final_file_approval(g.tenant_id, presentation_id, status='approved')
    if not approval:
        return False
    if export_row.get('content_hash') and approval.get('request_hash') \
            and export_row['content_hash'] == approval['request_hash']:
        return True
    if approval.get('stamped_export_id') and approval['stamped_export_id'] == export_row.get('id'):
        return True
    if approval.get('content_hash') and export_row.get('file_path'):
        path = export_row['file_path']
        if not os.path.isabs(path):
            path = os.path.join(app.root_path, path)
        return bool(db._file_sha256(path)) and db._file_sha256(path) == approval['content_hash']
    return False


@app.route('/api/exports/<export_id>/download', methods=['GET'])
@require_auth
def api_download_export(export_id):
    """Serve an export. Only officially approved files download without the
    draft marker — anything else needs the explicit ?draft=1 flag and ships
    with a DRAFT- filename prefix and an X-Draft-Mode header (t15-06).
    Financial study reports never enter the final-file approval flow, so the
    gate does not apply to them."""
    exported_file = db.get_export(export_id, g.tenant_id)
    if not exported_file:
        return jsonify({'error': 'Export not found'}), 404
    export_pres = db.get_presentation(exported_file['presentation_id'], tenant_id=g.tenant_id) \
        if exported_file.get('presentation_id') else None
    if export_pres and export_pres.get('draft_id'):
        accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
        if accessible is not None and export_pres['draft_id'] not in accessible:
            return jsonify({'error': 'Export not found'}), 404
    file_path = os.path.abspath(exported_file['file_path'])
    tenant_output_dir = os.path.abspath(os.path.join(OUTPUT_DIR, g.tenant_id))
    if os.path.commonpath([file_path, tenant_output_dir]) != tenant_output_dir or not os.path.isfile(file_path):
        return jsonify({'error': 'Export file unavailable'}), 404
    official = exported_file.get('format') == 'financial_pdf' or _export_is_official_row(exported_file)
    draft_requested = request.args.get('draft') in ('1', 'true')
    if not official and not draft_requested:
        return jsonify({'error': 'الملف غير معتمد نهائيًا — التنزيل الرسمي بعد الاعتماد فقط',
                        'error_code': 'final_approval_required'}), 403
    basename = os.path.basename(file_path)
    response = send_file(file_path, as_attachment=True,
                         download_name=basename if official else f'DRAFT-{basename}')
    if not official:
        response.headers['X-Draft-Mode'] = '1'
    return response
